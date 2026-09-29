"""下载计划的数据模型：把「工作流解析结果 + 本地查重 + 魔搭来源」合并成一份可执行计划。

计划的数据形状同时是 Web API 的响应契约（见 server.py）。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .mapping import CATEGORY_DIRS, primary_dir
from .parser import ModelRef, ParseResult
from .scan import LocalHit, LocalIndex
from .verify import human_bytes


class SourceKind(str, Enum):
    CURATED = "curated"      # 命中内置/本地维护的别名表
    SEARCH = "search"        # 魔搭站内搜索命中
    FILENAME = "filename"    # 仓库内文件名模糊匹配命中
    OVERRIDE = "override"    # 用户在 UI 里手工指定
    URL = "url"              # 用户在 UI 里粘贴的直连 URL（私有仓库/镜像入口）
    NONE = "none"            # 未找到可信来源，需人工确认


class Confidence(str, Enum):
    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"
    NONE = "无"


def _confidence(score: float, kind: SourceKind) -> Confidence:
    if kind is SourceKind.NONE or score <= 0:
        return Confidence.NONE
    if kind is SourceKind.CURATED or kind is SourceKind.OVERRIDE or score >= 0.9:
        return Confidence.HIGH
    if score >= 0.7:
        return Confidence.MEDIUM
    return Confidence.LOW


@dataclass(frozen=True, slots=True)
class Candidate:
    """一个备选来源。"""

    repo_id: str
    file_path: str
    score: float
    size: int | None = None
    sha256: str | None = None
    repo_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_id": self.repo_id,
            "repo_url": self.repo_url or f"https://www.modelscope.cn/models/{self.repo_id}",
            "file_path": self.file_path,
            "score": round(self.score, 3),
            "size": self.size,
        }


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    """模型在魔搭上的来源。"""

    kind: SourceKind
    repo_id: str = ""
    file_path: str = ""
    size: int | None = None
    sha256: str | None = None
    score: float = 0.0
    revision: str | None = None
    url: str = ""            # 直连下载 URL（SourceKind.URL 时使用，keyword-only）
    candidates: tuple[Candidate, ...] = ()

    @property
    def repo_url(self) -> str:
        if self.url:
            return self.url
        return f"https://www.modelscope.cn/models/{self.repo_id}" if self.repo_id else ""

    @property
    def confidence(self) -> Confidence:
        if self.kind is SourceKind.URL:
            return Confidence.HIGH
        return _confidence(self.score, self.kind)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "repo_id": self.repo_id,
            "repo_url": self.repo_url,
            "file_path": self.file_path,
            "url": self.url,
            "size": self.size,
            "sha256": self.sha256,
            "revision": self.revision,
            "score": round(self.score, 3),
            "confidence_label": self.confidence.value,
            "candidates": [c.to_dict() for c in self.candidates],
        }


@dataclass(slots=True)
class PlanItem:
    """计划中的一行：一个工作流引用的模型。"""

    item_id: int
    ref: ModelRef
    local: LocalHit
    source: ResolvedSource
    selected: bool = True
    target_rel: str = ""

    def __post_init__(self) -> None:
        if not self.target_rel:
            self.target_rel = f"{primary_dir(self.ref.category or 'checkpoints')}/{self.ref.filename}"

    @property
    def category(self) -> str | None:
        return self.ref.category

    @property
    def needs_download(self) -> bool:
        return (
            self.ref.category is not None
            and not self.local.exists
            and self.source.kind is not SourceKind.NONE
        )

    @property
    def is_unresolved(self) -> bool:
        return self.source.kind is SourceKind.NONE

    def to_dict(self) -> dict[str, Any]:
        size = self.source.size
        return {
            "id": self.item_id,
            "filename": self.ref.filename,
            "category": self.category,
            "category_dir": primary_dir(self.category) if self.category else None,
            "target_rel": self.target_rel,
            "node_id": self.ref.node_id,
            "class_type": self.ref.class_type,
            "input_name": self.ref.input_name,
            "size": size,
            "size_human": human_bytes(size),
            "selected": self.selected,
            "needs_download": self.needs_download,
            "unresolved": self.is_unresolved,
            "local": {
                "status": self.local.status,
                "path": str(self.local.file.path) if self.local.file else None,
                "size": self.local.file.size if self.local.file else None,
                "note": self.local.note,
            },
            "source": self.source.to_dict(),
        }


@dataclass(slots=True)
class Plan:
    """完整下载计划。"""

    job_id: str
    workflow_name: str
    parse: ParseResult
    items: list[PlanItem] = field(default_factory=list)
    comfy_root: str = ""
    models_dir: str = ""

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    @property
    def downloadable(self) -> list[PlanItem]:
        return [i for i in self.items if i.selected and i.needs_download]

    @property
    def unresolved(self) -> list[PlanItem]:
        return [i for i in self.items if i.is_unresolved]

    def by_id(self, item_id: int) -> PlanItem | None:
        return next((i for i in self.items if i.item_id == item_id), None)

    def totals(self) -> dict[str, Any]:
        present = sum(1 for i in self.items if i.local.exists)
        missing = sum(1 for i in self.items if not i.local.exists)
        to_download = [i for i in self.items if i.needs_download and i.selected]
        corrupt = sum(1 for i in self.items if i.local.status == "corrupt")
        unresolved = sum(1 for i in self.items if i.is_unresolved and not i.local.exists)
        no_category = sum(1 for i in self.items if i.ref.category is None)
        pending_bytes = sum(i.source.size or 0 for i in to_download)
        return {
            "total": len(self.items),
            "present": present,
            "missing": missing,
            "corrupt": corrupt,
            "to_download": len(to_download),
            "unresolved": unresolved + no_category,
            "no_category": no_category,
            "bytes_to_download": pending_bytes,
            "bytes_to_download_human": human_bytes(pending_bytes),
        }

    def summary(self) -> dict[str, Any]:
        by_cat: dict[str, int] = {}
        for i in self.items:
            key = i.category or "?"
            by_cat[key] = by_cat.get(key, 0) + 1
        return {
            "job_id": self.job_id,
            "workflow_name": self.workflow_name,
            "comfy_root": self.comfy_root,
            "models_dir": self.models_dir,
            "parse": self.parse.summary(),
            "by_category": by_cat,
            "totals": self.totals(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.summary(),
            "items": [i.to_dict() for i in self.items],
        }


#: 解析器接口：(category, filename, ref) -> ResolvedSource | None
Resolver = Callable[[str, str, ModelRef], ResolvedSource | None]


def build_plan(
    job_id: str,
    workflow_name: str,
    parse_result: ParseResult,
    local_index: LocalIndex,
    resolver: Resolver | None = None,
    models_dir: str = "",
    comfy_root: str = "",
    overrides: dict[int, ResolvedSource] | None = None,
    allow_basename_match: bool = True,
) -> Plan:
    """合并解析结果、本地索引与来源匹配，生成下载计划。

    resolver 允许为 None —— 此时只做本地查重，全部来源标为 none（离线可用）。
    """
    overrides = overrides or {}
    plan = Plan(
        job_id=job_id,
        workflow_name=workflow_name,
        parse=parse_result,
        models_dir=models_dir,
        comfy_root=comfy_root,
    )
    next_id = 1
    for ref in parse_result.refs:
        category = ref.category
        if category is None:
            plan.items.append(
                PlanItem(
                    item_id=next_id,
                    ref=ref,
                    local=LocalHit(ref.filename, "", "missing", None, "未能判定 ComfyUI 模型类别"),
                    source=ResolvedSource(SourceKind.NONE),
                    selected=False,
                )
            )
            next_id += 1
            continue

        hit = local_index.lookup(category, ref.filename)
        if hit.status == "basename" and not allow_basename_match:
            hit = LocalHit(ref.filename, category, "missing", hit.file,
                            "同名文件位于其他目录，按严格模式重新下载")

        source = overrides.get(next_id)
        if source is None and resolver is not None:
            source = resolver(category, ref.filename, ref)
        if source is None:
            source = ResolvedSource(SourceKind.NONE)

        plan.items.append(
            PlanItem(
                item_id=next_id,
                ref=ref,
                local=hit,
                source=source,
                selected=hit.status != "exact",
            )
        )
        next_id += 1

    # 未定类的引用也一并带出，便于 UI 提示人工处理
    for ref in parse_result.unresolved:
        plan.items.append(
            PlanItem(
                item_id=next_id,
                ref=ref,
                local=LocalHit(ref.filename, "", "missing", None, "未能判定 ComfyUI 模型类别"),
                source=ResolvedSource(SourceKind.NONE),
                selected=False,
            )
        )
        next_id += 1

    return plan


def categories_of(plan: Plan) -> Iterable[str]:
    seen = {i.category for i in plan.items if i.category}
    return (c for c in CATEGORY_DIRS if c in seen)
