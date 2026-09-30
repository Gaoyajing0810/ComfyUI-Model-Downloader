"""本地 ComfyUI 模型目录扫描与查重。

对应 ComfyUI 的 ``models/`` 布局，多根目录类别（unet + diffusion_models、
text_encoders + clip、controlnet + t2i_adapter）需要全部扫描。
"""

from __future__ import annotations

import os
import posixpath
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .mapping import all_dirs, extensions_for, primary_dir
from .verify import SafetensorsProbe, probe_safetensors

#: 判定 ComfyUI 根目录的标志文件
_ROOT_MARKERS = ("folder_paths.py", "main.py", "execution.py", "models")

_MAX_WALK_DEPTH: int = 12
_MAX_WALK_FILES: int = 50_000


@dataclass(slots=True)
class ComfyRoot:
    """一个 ComfyUI 安装的定位信息。"""

    root: Path
    models_dir: Path

    @classmethod
    def resolve(cls, comfy_root: str | Path | None, models_dir: str | Path | None = None) -> ComfyRoot:
        if models_dir is not None:
            md = Path(models_dir).expanduser().resolve()
            root = md.parent if md.name == "models" else comfy_root and Path(comfy_root).expanduser().resolve() or md.parent
            return cls(root=root, models_dir=md)

        if comfy_root is None:
            raise ValueError("必须指定 --comfy-root 或 --models-dir")
        root = Path(comfy_root).expanduser().resolve()
        if (root / "folder_paths.py").exists() or (root / "main.py").exists():
            models = root / "models"
            if models.is_dir():
                return cls(root=root, models_dir=models)
            # models 目录还不存在时按默认布局建
            return cls(root=root, models_dir=models)
        if root.name == "models":
            return cls(root=root.parent, models_dir=root)
        raise ValueError(
            f"{root} 不像 ComfyUI 根目录（缺少 folder_paths.py / main.py）。"
            " 若模型目录在别处，请直接用 --models-dir 指定。"
        )

    def category_dir(self, category: str) -> Path:
        return self.models_dir / primary_dir(category)

    def rel_category_dir(self, category: str) -> str:
        return primary_dir(category)

    def target_path(self, category: str, filename: str) -> Path:
        return self.models_dir / primary_dir(category) / filename

    def ensure_category_dir(self, category: str) -> Path:
        d = self.category_dir(category)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def to_dict(self) -> dict[str, str]:
        return {"root": str(self.root), "models_dir": str(self.models_dir)}


@dataclass(frozen=True, slots=True)
class LocalFile:
    category: str
    rel_path: str          # 相对 models/ 的路径，如 checkpoints/xxx.safetensors
    path: Path
    size: int
    healthy: bool | None = None   # None=未检查, True=正常, False=文件头损坏/HTML 错误页


@dataclass(frozen=True, slots=True)
class LocalHit:
    """一次查重结果。"""

    filename: str
    category: str
    status: str                       # "exact" | "basename" | "missing" | "corrupt"
    file: LocalFile | None = None
    note: str = ""

    @property
    def exists(self) -> bool:
        return self.status in ("exact", "basename")


@dataclass(slots=True)
class LocalIndex:
    """按类别建立的本地文件索引。"""

    models_dir: Path
    _by_category: dict[str, dict[str, LocalFile]] = field(default_factory=dict)
    _base_by_category: dict[str, dict[str, list[LocalFile]]] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        root: ComfyRoot,
        categories: Iterable[str] | None = None,
        health_check: bool = True,
    ) -> LocalIndex:
        idx = cls(models_dir=root.models_dir)
        cats = list(categories) if categories is not None else None
        if cats is None:
            from .mapping import CATEGORY_DIRS

            cats = list(CATEGORY_DIRS)
        for cat in cats:
            by_rel: dict[str, LocalFile] = {}
            by_base: dict[str, list[LocalFile]] = {}
            for dirname in all_dirs(cat):
                base = root.models_dir / dirname
                if not base.is_dir():
                    continue
                for f in _walk_model_files(base, cat, health_check):
                    rel = f"{dirname}/{f.rel}"
                    lf = LocalFile(category=cat, rel_path=rel, path=f.abs, size=f.size, healthy=f.healthy)
                    by_rel[rel.lower()] = lf
                    by_base.setdefault(f.abs.name.lower(), []).append(lf)
            idx._by_category[cat] = by_rel
            idx._base_by_category[cat] = by_base
        return idx

    # -- 查询 ---------------------------------------------------------------

    def lookup(self, category: str, filename: str) -> LocalHit:
        """按类别 + 相对文件名查重。"""
        filename = filename.replace("\\", "/").lstrip("/")
        rel_norm = posixpath.join(primary_dir(category), filename).lower()
        by_rel = self._by_category.get(category, {})
        lf = by_rel.get(rel_norm)
        if lf is not None:
            if lf.healthy is False:
                return LocalHit(filename, category, "corrupt", lf,
                                "文件存在但内容损坏（疑似错误页/截断），建议重新下载")
            return LocalHit(filename, category, "exact", lf)

        by_base = self._base_by_category.get(category, {})
        matches = by_base.get(posixpath.basename(filename).lower(), [])
        if matches:
            # 同类别下同名文件（可能子目录不同）：视为已存在，附注实际路径
            exact_sub = [m for m in matches if posixpath.basename(m.rel_path) == posixpath.basename(filename)]
            chosen = sorted(matches, key=lambda m: len(m.rel_path))[0]
            note = f"已存在于 {chosen.rel_path}"
            if len(matches) > 1:
                note += f"（该类别下有 {len(matches)} 个同名文件）"
            return LocalHit(filename, category, "basename", chosen, note)
        return LocalHit(filename, category, "missing", None)

    def list_category(self, category: str) -> list[LocalFile]:
        return sorted(self._by_category.get(category, {}).values(), key=lambda f: f.rel_path)

    def stats(self) -> dict[str, dict[str, int]]:
        return {
            cat: {"files": len(files), "bytes": sum(f.size for f in files.values())}
            for cat, files in self._by_category.items()
            if files
        }


@dataclass(frozen=True, slots=True)
class _WalkedFile:
    rel: str
    abs: Path
    size: int
    healthy: bool | None


def _walk_model_files(base: Path, category: str, health_check: bool) -> Iterator[_WalkedFile]:
    allowed = extensions_for(category)
    file_count = 0
    base_parts = len(base.parts)
    for dirpath, dirnames, filenames in os.walk(base):
        depth = len(Path(dirpath).parts) - base_parts
        if depth >= _MAX_WALK_DEPTH:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith(".") or name.endswith((".part", ".tmp", ".download")):
                continue
            ext = posixpath.splitext(name)[1].lower()
            if allowed is not None and ext not in allowed:
                continue
            p = Path(dirpath) / name
            try:
                size = p.stat().st_size
            except OSError:
                continue
            healthy: bool | None = None
            if health_check and ext == ".safetensors":
                healthy = probe_safetensors(p).ok
            yield _WalkedFile(name, p, size, healthy)
            file_count += 1
            if file_count >= _MAX_WALK_FILES:
                raise ValueError(
                    f"{base} 文件数超过 {_MAX_WALK_FILES} 上限（depth 限制 {_MAX_WALK_DEPTH}）"
                )


def iter_model_files(root: ComfyRoot, category: str, health_check: bool = False) -> Iterator[Path]:
    """遍历某个类别在所有子目录下的模型文件（绝对路径）。"""
    seen: set[Path] = set()
    for d in all_dirs(category):
        for wf in _walk_model_files(root.models_dir / d, category, health_check):
            if wf.abs not in seen:
                seen.add(wf.abs)
                yield wf.abs
