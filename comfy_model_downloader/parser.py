"""ComfyUI workflow JSON 解析。

支持三种常见形态：
  1. API 格式（ComfyUI ``/prompt`` 载荷）—— 顶层是 ``{node_id: {class_type, inputs}}``
  2. UI 格式（导出的 workflow）—— ``{"nodes": [{"type": ..., "widgets_values": [...]}]}``
  3. 新版前端格式 —— ``{"state": {"nodes": [...]}, "definitions": {"subgraphs": [...]}}``

UI 格式的 ``widgets_values`` 是**位置型**的，拿不到输入名，因此：
  - 已知节点按 WIDGET_ORDER 对位，未对上的位置再靠文件名规则兜底
  - ``widgets_values`` 是 dict 时可直接按输入名匹配
"""

from __future__ import annotations

import json
import posixpath
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .mapping import (
    WIDGET_ORDER,
    guess_category,
    looks_like_model_file,
    sanitize_subpath,
)


@dataclass(frozen=True, slots=True)
class ModelRef:
    """工作流里的一条模型引用。"""

    filename: str
    category: str | None
    rule: str
    confidence: float
    class_type: str = ""
    input_name: str = ""
    node_id: str = ""

    @property
    def basename(self) -> str:
        return posixpath.basename(self.filename)

    @property
    def subdir(self) -> str:
        return posixpath.dirname(self.filename)

    def identity(self) -> tuple[str, str]:
        """去重键：类别 + 小写文件名。"""
        return (self.category or "", self.filename.lower())


@dataclass(slots=True)
class ParseResult:
    refs: list[ModelRef] = field(default_factory=list)
    unresolved: list[ModelRef] = field(default_factory=list)
    node_count: int = 0
    subgraph_count: int = 0
    fmt: str = "unknown"
    notes: list[str] = field(default_factory=list)

    @property
    def resolved(self) -> list[ModelRef]:
        return self.refs

    def summary(self) -> dict[str, Any]:
        by_cat: dict[str, int] = {}
        for r in self.refs:
            by_cat[r.category or "?"] = by_cat.get(r.category or "?", 0) + 1
        return {
            "format": self.fmt,
            "nodes_scanned": self.node_count,
            "subgraphs": self.subgraph_count,
            "models_resolved": len(self.refs),
            "models_unresolved": len(self.unresolved),
            "by_category": by_cat,
            "notes": self.notes,
        }


class WorkflowParseError(ValueError):
    """workflow 结构无法识别。"""


def _count_subgraphs(data: dict[str, Any]) -> int:
    """统计嵌套子图数量（新版前端的 definitions.subgraphs / 顶层 subgraphs）。"""
    total = 0
    for key in ("subgraphs",):
        val = data.get(key)
        if isinstance(val, list):
            total += len(val)
    defs = data.get("definitions")
    if isinstance(defs, dict) and isinstance(defs.get("subgraphs"), list):
        total += len(defs["subgraphs"])
    return total


def _accept(value: str, category: str | None) -> bool:
    """一个字符串是否可作为模型文件名接受。

    ComfyUI 里模型输入框的取值一定是带扩展名的文件名，因此必须校验扩展名；
    否则 weight_dtype="default"、DualCLIPLoader.type="flux" 这类枚举值会被误当成模型。
    """
    return looks_like_model_file(value, category)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def load_workflow(source: str | Path | dict[str, Any] | bytes) -> ParseResult:
    """从文件路径 / JSON 字符串 / dict / bytes 加载并解析 workflow。"""
    if isinstance(source, dict):
        data: Any = source
    elif isinstance(source, Path):
        data = _read_workflow_file(source)
    elif isinstance(source, bytes):
        try:
            data = json.loads(source.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkflowParseError(f"上传的内容不是合法的 UTF-8 JSON：{exc}") from exc
    else:
        try:
            data = json.loads(source)
        except json.JSONDecodeError:
            data = _read_workflow_file(Path(source))
    return parse_workflow(data)


def _read_workflow_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise WorkflowParseError(f"无法读取 workflow 文件 {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise WorkflowParseError(f"{path} 不是合法的 JSON 文件: {exc}") from exc


def parse_workflow(data: Any) -> ParseResult:
    """解析已加载的 workflow 数据。"""
    if not isinstance(data, dict):
        raise WorkflowParseError(f"workflow 顶层必须是对象，实际是 {type(data).__name__}")

    result = ParseResult()
    result.subgraph_count = _count_subgraphs(data)
    collectors: list[tuple[str, list[ModelRef]]] = []
    collectors.append(("root", _parse_api_format(data, result)))
    for node_map in _iter_node_maps(data, result):
        collectors.append(("ui", _parse_ui_format(node_map, result)))
    for node_map in _iter_api_node_maps(data, result):
        collectors.append(("api", _parse_api_node_map(node_map, result)))

    if not collectors:
        raise WorkflowParseError(
            "未在工作流中找到任何节点。请确认上传的是 ComfyUI 导出的 workflow JSON"
            "（含 nodes 或 class_type），而不是图片/提示词文本。"
        )

    seen: set[tuple[str, str]] = set()
    for _label, refs in collectors:
        for ref in refs:
            key = ref.identity()
            if key in seen:
                continue
            seen.add(key)
            if ref.category is None:
                result.unresolved.append(ref)
            else:
                result.refs.append(ref)

    result.refs.sort(key=lambda r: (r.category or "", r.filename.lower()))
    result.unresolved.sort(key=lambda r: r.filename.lower())
    return result


# ---------------------------------------------------------------------------
# API 格式
# ---------------------------------------------------------------------------


def _looks_like_api_format(data: dict[str, Any]) -> bool:
    values = list(data.values())
    if not values:
        return False
    hits = sum(
        1
        for v in values
        if isinstance(v, dict) and "class_type" in v and isinstance(v.get("inputs"), dict)
    )
    return hits >= 1 and hits >= len(values) / 2


def _parse_api_format(data: dict[str, Any], result: ParseResult) -> list[ModelRef]:
    if not _looks_like_api_format(data):
        return []
    result.fmt = "api"
    return _parse_api_node_map(data, result)


def _parse_api_node_map(node_map: dict[str, Any], result: ParseResult) -> list[ModelRef]:
    refs: list[ModelRef] = []
    for node_id, node in node_map.items():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type") or node.get("type") or "")
        inputs = node.get("inputs")
        result.node_count += 1
        if not isinstance(inputs, dict):
            continue
        for input_name, value in inputs.items():
            if not isinstance(value, str):
                continue
            guess = guess_category(class_type, input_name, value)
            if not _accept(value, guess.category):
                continue
            try:
                filename = sanitize_subpath(value)
            except ValueError:
                continue
            refs.append(
                ModelRef(
                    filename=filename,
                    category=guess.category,
                    rule=guess.rule,
                    confidence=guess.confidence,
                    class_type=class_type,
                    input_name=input_name,
                    node_id=str(node_id),
                )
            )
    return refs


def _iter_api_node_maps(data: dict[str, Any], result: ParseResult) -> Iterator[dict[str, Any]]:
    """找出 API 格式节点集合（含 subgraph 里的 prompt 集合）。"""
    stack: list[Any] = [data]
    seen: set[int] = set()
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if id(cur) in seen:
                continue
            seen.add(id(cur))
            if _looks_like_api_format(cur):
                yield cur
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


# ---------------------------------------------------------------------------
# UI 格式
# ---------------------------------------------------------------------------


def _iter_node_maps(data: dict[str, Any], result: ParseResult) -> Iterator[dict[str, Any]]:
    """遍历所有持有 ``nodes`` 列表的位置，含 subgraph 定义。"""
    stack: list[Any] = [data]
    seen: set[int] = set()
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if id(cur) in seen:
                continue
            seen.add(id(cur))
            for key in ("state", "subgraphs", "definitions", "extra"):
                sub = cur.get(key)
                if isinstance(sub, (dict, list)):
                    stack.append(sub)
            nodes = cur.get("nodes")
            if isinstance(nodes, list):
                if result.fmt == "unknown":
                    result.fmt = "ui"
                yield {str(n.get("id", i)): n for i, n in enumerate(nodes) if isinstance(n, dict)}
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def _parse_ui_format(node_map: dict[str, Any], result: ParseResult) -> list[ModelRef]:
    refs: list[ModelRef] = []
    for node_id, node in node_map.items():
        result.node_count += 1
        refs.extend(_parse_ui_node(node_id, node))
    return refs


def _parse_ui_node(node_id: str, node: dict[str, Any]) -> list[ModelRef]:
    class_type = str(node.get("type") or "")
    widgets = node.get("widgets_values")
    if widgets is None:
        widgets = node.get("inputs", {}).get("values") if isinstance(node.get("inputs"), dict) else None
    if widgets is None:
        return []
    if isinstance(widgets, dict):
        return _parse_ui_widget_dict(node_id, class_type, widgets)
    if isinstance(widgets, list):
        return _parse_ui_widget_list(node_id, class_type, widgets)
    return []


def _parse_ui_widget_dict(node_id: str, class_type: str, widgets: dict[str, Any]) -> list[ModelRef]:
    refs: list[ModelRef] = []
    for input_name, value in widgets.items():
        if not isinstance(value, str):
            continue
        guess = guess_category(class_type, str(input_name), value)
        if not _accept(value, guess.category):
            continue
        try:
            filename = sanitize_subpath(value)
        except ValueError:
            continue
        refs.append(
            ModelRef(filename, guess.category, guess.rule, guess.confidence,
                     class_type, str(input_name), node_id)
        )
    return refs


def _parse_ui_widget_list(node_id: str, class_type: str, widgets: list[Any]) -> list[ModelRef]:
    order = WIDGET_ORDER.get(class_type)
    refs: list[ModelRef] = []
    for idx, value in enumerate(widgets):
        if not isinstance(value, str):
            continue
        # 位置能对上的输入名才有意义，且仅在值像模型名时采用
        input_name = order[idx] if order is not None and idx < len(order) else None
        guess = guess_category(class_type, input_name, value)
        if not _accept(value, guess.category):
            continue
        try:
            filename = sanitize_subpath(value)
        except ValueError:
            continue
        refs.append(
            ModelRef(filename, guess.category, guess.rule, guess.confidence,
                     class_type, input_name or f"widget[{idx}]", node_id)
        )
    return refs


def iter_model_strings(data: Any) -> Iterable[str]:
    """深度遍历，产出所有像模型路径的字符串。用于解析失败时的兜底诊断。"""
    stack: list[Any] = [data]
    while stack:
        cur = stack.pop()
        if isinstance(cur, str):
            if looks_like_model_file(cur):
                yield cur
        elif isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
