"""ComfyUI Model Downloader —— 从 ComfyUI 工作流自动解析模型清单并经 ModelScope 下载到本地模型目录。"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    # 优先读 pyproject.toml（PEP 621）→ importlib.metadata，这是真相源。
    __version__ = _pkg_version("comfy-ui-model-downloader")
except PackageNotFoundError:
    # 兜底：源码树直跑 / frozen 打包未收集 .dist-info 等极端场景。
    # 由 scripts/bump_version.py 与 pyproject 同步维护。
    __version__ = "0.1.11"
from .mapping import CATEGORY_DIRS, primary_dir
from .parser import ModelRef, ParseResult, load_workflow, parse_workflow
from .plan import Plan, PlanItem, ResolvedSource, SourceKind, build_plan
from .scan import ComfyRoot, LocalIndex
from .verify import VerifyResult, VerifyStatus, verify_file

__all__ = [
    "__version__",
    "CATEGORY_DIRS",
    "primary_dir",
    "ModelRef",
    "ParseResult",
    "load_workflow",
    "parse_workflow",
    "Plan",
    "PlanItem",
    "ResolvedSource",
    "SourceKind",
    "build_plan",
    "ComfyRoot",
    "LocalIndex",
    "VerifyResult",
    "VerifyStatus",
    "verify_file",
]
