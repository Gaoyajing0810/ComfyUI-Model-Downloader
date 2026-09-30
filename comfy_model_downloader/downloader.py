"""下载编排：并发限流、断点续传、原子落盘、失败重试、进度上报。

本模块不认识 ModelScope，只依赖 `ModelFetcher` 协议——由 modelscope_client 实现。
"""

from __future__ import annotations

import asyncio
import shutil
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from .cleanup import _AGE_SECONDS_AFTER_DOWNLOAD, cleanup_stale_parts
from .config import Settings
from .mapping import safe_join
from .plan import Plan, PlanItem, ResolvedSource, SourceKind
from .verify import VerifyStatus, human_bytes, verify_file


class DownloadState(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"
    UNRESOLVED = "unresolved"


ProgressFn = Callable[[int, int], None]
CancelFn = Callable[[], bool]


class ModelFetcher(Protocol):
    """把一个魔搭来源落到本地目标路径。"""

    async def fetch(
        self,
        source: ResolvedSource,
        dest: Path,
        *,
        on_progress: ProgressFn,
        should_cancel: CancelFn,
    ) -> dict[str, Any]:
        """下载并原子落盘，返回含 bytes/sha256 的元数据。"""
        ...


@dataclass(slots=True)
class ItemProgress:
    item_id: int
    filename: str
    category: str | None
    state: DownloadState = DownloadState.PENDING
    downloaded: int = 0
    total: int = 0
    speed_bps: float = 0.0
    message: str = ""
    error: str | None = None
    dest: str = ""
    sha256: str | None = None

    @property
    def progress(self) -> float:
        return 1.0 if self.total <= 0 else min(1.0, self.downloaded / self.total)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.item_id,
            "filename": self.filename,
            "category": self.category,
            "state": self.state.value,
            "progress": round(self.progress, 4),
            "downloaded": self.downloaded,
            "total": self.total,
            "downloaded_human": human_bytes(self.downloaded),
            "total_human": human_bytes(self.total),
            "speed_bps": round(self.speed_bps, 1),
            "message": self.message,
            "error": self.error,
            "dest": self.dest,
        }


@dataclass(slots=True)
class DownloadTask:
    task_id: str
    workflow_name: str
    models_dir: str
    items: list[ItemProgress] = field(default_factory=list)
    state: str = "running"
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    _cancel: bool = False
    _log: list[str] = field(default_factory=list)

    def cancel(self) -> None:
        self._cancel = True

    @property
    def cancelled(self) -> bool:
        return self._cancel

    def log(self, line: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self._log.append(f"[{stamp}] {line}")
        del self._log[:-500]

    def overall(self) -> dict[str, Any]:
        done = sum(1 for i in self.items if i.state is DownloadState.DONE)
        failed = sum(1 for i in self.items if i.state is DownloadState.FAILED)
        total = len(self.items)
        got = sum(i.downloaded for i in self.items)
        want = sum(i.total for i in self.items)
        speed = sum(i.speed_bps for i in self.items)
        elapsed = (self.finished_at or time.time()) - self.started_at
        eta = (want - got) / speed if speed > 1 and want > got else 0.0
        return {
            "done": done,
            "failed": failed,
            "total": total,
            "bytes": got,
            "total_bytes": want,
            "speed_bps": round(speed, 1),
            "speed_human": f"{speed / 1048576:.2f} MB/s",
            "eta_seconds": round(eta, 1),
            "progress": round(got / want, 4) if want else (1.0 if total and done == total else 0.0),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "workflow_name": self.workflow_name,
            "models_dir": self.models_dir,
            "state": self.state,
            "cancelled": self._cancel,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.started_at)),
            "overall": self.overall(),
            "items": [i.to_dict() for i in self.items],
        }

    def to_history(self) -> dict[str, Any]:
        o = self.overall()
        return {
            "task_id": self.task_id,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.started_at)),
            "workflow_name": self.workflow_name,
            "state": self.state,
            "done": o["done"],
            "total": o["total"],
            "bytes": o["bytes"],
        }


class _SpeedMeter:
    """指数滑动平均速率，兼作节流后的进度上报器。"""

    __slots__ = ("_last", "_last_time", "_ema", "_last_emit")

    def __init__(self) -> None:
        self._last = 0
        self._last_time = time.monotonic()
        self._ema = 0.0
        self._last_emit = 0.0

    def feed(self, done: int, total: int, emit: ProgressFn) -> None:
        now = time.monotonic()
        delta = done - self._last
        dt = now - self._last_time
        if dt > 0.2 and delta > 0:
            inst = delta / dt
            self._ema = inst if self._ema == 0 else self._ema * 0.7 + inst * 0.3
            self._last, self._last_time = done, now
        if now - self._last_emit > 0.25 or done >= total:
            self._last_emit = now
            emit(done, total)

    @property
    def bps(self) -> float:
        return self._ema


async def _download_one(
    item: PlanItem,
    progress: ItemProgress,
    models_root: Path,
    fetcher: ModelFetcher,
    settings: Settings,
    task: DownloadTask,
) -> None:
    source = item.source
    assert source.kind is not SourceKind.NONE
    try:
        dest = safe_join(models_root, item.target_rel)
    except ValueError as exc:
        progress.state = "failed"
        progress.error = f"路径安全检查未通过：{exc}"
        task.log(f"路径安全检查未通过：{exc}")
        return
    progress.dest = str(dest)
    progress.total = source.size or 0
    meter = _SpeedMeter()

    def on_progress(done: int, total: int) -> None:
        progress.downloaded = done
        if total:
            progress.total = total
        progress.speed_bps = meter.bps
        progress.message = f"已下载 {human_bytes(done)}"

    last_error: Exception | None = None
    for attempt in range(1, settings.retries + 1):
        if task.cancelled:
            progress.state = DownloadState.PENDING
            progress.message = "已取消"
            return
        progress.state = DownloadState.DOWNLOADING
        progress.message = f"下载中（第 {attempt}/{settings.retries} 次尝试）"
        task.log(f"开始下载 {item.ref.filename} -> {item.target_rel}")
        try:
            meta = await fetcher.fetch(
                source,
                dest,
                on_progress=on_progress,
                should_cancel=lambda: task.cancelled,
            )
            progress.sha256 = meta.get("sha256")
            if meta.get("size"):
                progress.total = int(meta["size"])
            break
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 逐项容错，单个失败不终止整批
            last_error = exc
            task.log(f"失败 {item.ref.filename}: {exc}")
            progress.speed_bps = 0.0
            if attempt < settings.retries:
                await asyncio.sleep(min(2 ** attempt, 10))
    else:
        progress.state = DownloadState.FAILED
        progress.error = str(last_error)
        progress.message = f"下载失败：{last_error}"
        return

    if task.cancelled:
        progress.state = DownloadState.PENDING
        progress.message = "已取消"
        return

    progress.state = DownloadState.VERIFYING
    progress.message = "校验中"
    progress.speed_bps = 0.0
    result = await asyncio.to_thread(
        verify_file,
        dest,
        source.size,
        source.sha256,
        settings.deep_verify,
    )
    if result.status in ACCEPTED_STATUSES:
        progress.state = DownloadState.DONE
        progress.downloaded = progress.total or dest.stat().st_size
        suffix = "" if result.status is VerifyStatus.OK else "（远端未提供 sha256，已按文件头+大小校验）"
        progress.message = f"完成 · {human_bytes(dest.stat().st_size)}{suffix}"
        task.log(f"完成 {item.target_rel} ({result.status.value})")
    else:
        _quarantine(dest)
        progress.state = DownloadState.FAILED
        progress.error = f"{result.status.value}: {result.detail}"
        progress.message = f"校验未通过（{result.status.value}）"
        task.log(f"校验失败 {item.target_rel}: {result.detail}")


#: 视为下载成功的结果。远端未提供 sha256 时只能做文件头+大小校验，不该判为损坏。
ACCEPTED_STATUSES = frozenset({VerifyStatus.OK, VerifyStatus.NO_CHECKSUM})


def _quarantine(dest: Path) -> None:
    """校验失败的文件改名留存，不留在模型目录里冒充可用权重。"""
    try:
        if dest.exists():
            dest.replace(dest.with_suffix(dest.suffix + ".corrupt"))
    except OSError:
        pass


class DownloadManager:
    """持有进行中的任务，供 Web API 轮询。"""

    def __init__(self, settings: Settings, max_history: int = 50) -> None:
        self._settings = settings
        self._tasks: dict[str, DownloadTask] = {}
        self._order: list[str] = []
        self._max_history = max_history
        self._sem = asyncio.Semaphore(max(1, settings.concurrency))
        self._active_parts: set[Path] = set()

    def get(self, task_id: str) -> DownloadTask | None:
        return self._tasks.get(task_id)

    def history(self) -> list[dict[str, Any]]:
        return [self._tasks[t].to_history() for t in reversed(self._order) if t in self._tasks]

    def logs(self, task_id: str) -> list[str]:
        task = self._tasks.get(task_id)
        return list(task._log) if task else []

    def create(self, plan: Plan, item_ids: Sequence[int] | None = None) -> DownloadTask:
        wanted = set(item_ids) if item_ids else None
        items: list[ItemProgress] = []
        for i in plan.items:
            if wanted is not None and i.item_id not in wanted:
                continue
            if i.source.kind is SourceKind.NONE:
                items.append(
                    ItemProgress(
                        item_id=i.item_id,
                        filename=i.ref.filename,
                        category=i.ref.category,
                        state=DownloadState.UNRESOLVED,
                        message="未在魔搭找到可信来源",
                    )
                )
            elif i.local.exists:
                size = i.local.file.size if i.local.file else 0
                items.append(
                    ItemProgress(
                        item_id=i.item_id,
                        filename=i.ref.filename,
                        category=i.ref.category,
                        state=DownloadState.SKIPPED,
                        downloaded=size,
                        total=size,
                        message=f"本地已存在，跳过下载（{i.local.status}）",
                        dest=str(Path(plan.models_dir) / i.target_rel) if plan.models_dir else None,
                    )
                )
            else:
                items.append(
                    ItemProgress(
                        item_id=i.item_id,
                        filename=i.ref.filename,
                        category=i.ref.category,
                        total=i.source.size or 0,
                    )
                )
        task = DownloadTask(
            task_id=_new_id("t"),
            workflow_name=plan.workflow_name,
            models_dir=plan.models_dir,
            items=items,
        )
        self._tasks[task.task_id] = task
        self._order.append(task.task_id)
        del self._order[: -self._max_history]
        return task

    async def run(self, task: DownloadTask, plan: Plan, fetcher: ModelFetcher) -> DownloadTask:
        by_id = plan.by_id
        models_root = Path(task.models_dir)
        pending = [i for i in task.items if i.state is DownloadState.PENDING]
        sem = self._sem

        async def worker(progress: ItemProgress) -> None:
            item = by_id(progress.item_id)
            if item is None:
                progress.state = DownloadState.FAILED
                progress.error = "计划中找不到该条目"
                return
            async with sem:
                try:
                    await _download_one(item, progress, models_root, fetcher, self._settings, task)
                except asyncio.CancelledError:
                    progress.state = DownloadState.PENDING
                    progress.message = "已取消"
                    raise

        results = await asyncio.gather(*(worker(p) for p in pending), return_exceptions=True)
        for exc in results:
            if isinstance(exc, asyncio.CancelledError):
                if not task.cancelled:
                    raise exc
                task.state = "cancelled"
                task.finished_at = time.time()
                task.log("任务已取消")
                return task
            if isinstance(exc, BaseException):
                task.log(f"worker 异常（不影响其他任务）: {type(exc).__name__}: {exc}")
        states = {i.state for i in task.items}
        if DownloadState.FAILED in states:
            task.state = "failed"
        else:
            task.state = "done"
        task.finished_at = time.time()
        task.log(f"任务结束：{task.state}")
        removed = await asyncio.to_thread(
            cleanup_stale_parts,
            models_root,
            max_age_seconds=_AGE_SECONDS_AFTER_DOWNLOAD,
            active_paths=self._active_parts,
        )
        if removed:
            task.log(f"清理 {removed} 个陈旧 .part 残骸")
        return task


def _new_id(prefix: str) -> str:
    import secrets

    return f"{prefix}_{secrets.token_hex(4)}"


def free_disk_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free
