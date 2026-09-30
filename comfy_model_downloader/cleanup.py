"""Stale partial-download cleanup.

ComfyUI 模型下载是流式落盘，过程中先写 ``<name>.part``（见 modelscope_client / downloader）。
中断、断电、进程崩溃都会留下 ``.part`` 残骸，长期堆积会污染 ``data/models.json`` 索引、
浪费磁盘。工具启动时跑一次清理（默认 7 天阈值），下载成功路径里再跑一次（1 天阈值）
确保当前会话留下的半成品也跟着被收走。

设计原则：
* 只删 ``.part`` / ``.tmp`` / ``.download`` 三种后缀，不碰正式文件；
* 只删 mtime 早于阈值且 stat 成功的文件，规避 toctou；
* 单进程、串行；不做并发（量级小，IO 是次序的，磁盘抖动比并发收益大）；
* 失败静默：删除抛 OSError 时跳过该文件，不阻断其他文件清理。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

_PART_GLOBS: tuple[str, ...] = ("*.part", "*.tmp", "*.download")
_AGE_SECONDS_DEFAULT: int = 7 * 86400  # 启动清理默认 7 天
_AGE_SECONDS_AFTER_DOWNLOAD: int = 1 * 86400  # 下载完成后清理默认 1 天


def cleanup_stale_parts(
    models_dir: Path,
    *,
    max_age_seconds: int = _AGE_SECONDS_DEFAULT,
    active_paths: set[Path] | None = None,
    log: logging.Logger | None = None,
) -> int:
    """删除 ``models_dir`` 下早于 ``max_age_seconds`` 的 ``.part`` / ``.tmp`` / ``.download`` 残骸。

    返回成功删除的文件数。``models_dir`` 不存在或不是目录时返回 0。

    ``active_paths`` 是当前正在下载的目标 ``.part`` 路径集合——这些文件跳过删除，
    避免断点续传过程中被误删导致 GB 级数据丢失。
    """
    if not models_dir.is_dir():
        return 0
    cutoff = time.time() - max_age_seconds
    removed = 0
    for glob in _PART_GLOBS:
        for part in models_dir.rglob(glob):
            if active_paths and part in active_paths:
                continue
            try:
                if part.stat().st_mtime < cutoff:
                    part.unlink()
                    removed += 1
                    if log is not None:
                        log.info("stale partial removed: %s", part)
            except OSError:
                # 文件在扫描过程中被删、权限不足等——跳过
                continue
    return removed


__all__ = [
    "cleanup_stale_parts",
    "_AGE_SECONDS_DEFAULT",
    "_AGE_SECONDS_AFTER_DOWNLOAD",
]