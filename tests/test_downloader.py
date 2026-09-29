"""下载编排层测试：并发、重试、取消、损坏隔离。

用 FakeFetcher 代替真实 ModelScope，避免测试联网。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from comfy_model_downloader import mapping
from comfy_model_downloader.config import Settings
from comfy_model_downloader.downloader import DownloadManager, DownloadState
from comfy_model_downloader.parser import parse_workflow
from comfy_model_downloader.plan import ResolvedSource, SourceKind, build_plan
from comfy_model_downloader.scan import ComfyRoot, LocalIndex


def make_safetensors(payload_bytes: int = 64) -> bytes:
    """构造一个结构合法的最小 safetensors 字节串。"""
    header = json.dumps({"t": {"dtype": "F32", "shape": [1], "data_offsets": [0, payload_bytes]}})
    raw = header.encode("utf-8")
    pad = (-len(raw)) % 8
    raw += b" " * pad
    return len(raw).to_bytes(8, "little") + raw + b"\0" * payload_bytes


WORKFLOW = {
    "nodes": [
        {"id": 1, "type": "LoraLoader", "widgets_values": ["a.safetensors", 1, 1, "A"]},
        {"id": 2, "type": "LoraLoader", "widgets_values": ["b.safetensors", 1, 1, "B"]},
        {"id": 3, "type": "VAELoader", "widgets_values": ["c.safetensors"]},
    ]
}


def _root(tmp_path):
    for cat in ("loras", "vae"):
        (tmp_path / "models" / cat).mkdir(parents=True, exist_ok=True)
    return ComfyRoot.resolve(tmp_path, tmp_path / "models")


def _plan(tmp_path, sources=None):
    root = _root(tmp_path)
    index = LocalIndex.build(root, ["loras", "vae"], health_check=False)
    parsed = parse_workflow(WORKFLOW)

    def resolver(category, filename, ref):
        if sources is not None:
            return sources.get(filename)
        return ResolvedSource(SourceKind.SEARCH, repo_id=f"org/{filename[:-10]}",
                             file_path=filename, size=len(make_safetensors(64)), score=0.95)

    return build_plan("j1", "wf.json", parsed, index, resolver,
                      models_dir=str(root.models_dir), comfy_root=str(root.root))


class FakeFetcher:
    """按文件名决定成败的假下载器。"""

    def __init__(self, fail_times=0, payload=None, fail_files=()):
        self.calls: list[str] = []
        self.fail_times = fail_times
        self.payload = payload or {}
        self.fail_files = set(fail_files)
        self.concurrent = 0
        self.peak = 0

    async def fetch(self, source, dest, *, on_progress, should_cancel):
        self.calls.append(dest.name)
        self.concurrent += 1
        self.peak = max(self.peak, self.concurrent)
        try:
            for step in range(3):
                if should_cancel():
                    raise asyncio.CancelledError
                on_progress(step * 32, 96)
                await asyncio.sleep(0.01)
            data = self.payload.get(dest.name)
            if data is None:
                if self.fail_times > 0:
                    self.fail_times -= 1
                    raise RuntimeError("模拟网络中断")
                data = make_safetensors(64)
            dest.write_bytes(data)
            return {"sha256": "0" * 64, "size": len(data)}
        finally:
            self.concurrent -= 1


def test_downloads_all_and_verifies(tmp_path):
    plan = _plan(tmp_path)
    settings = Settings()
    manager = DownloadManager(settings)
    task = manager.create(plan, [i.item_id for i in plan.downloadable])
    fetcher = FakeFetcher()

    asyncio.run(manager.run(task, plan, fetcher))

    assert task.state == "done"
    states = {it.filename: it.state for it in task.items}
    assert all(s is DownloadState.DONE for s in states.values())
    for name in ("a.safetensors", "b.safetensors", "c.safetensors"):
        assert (tmp_path / "models" / ("vae" if name.startswith("c") else "loras") / name).is_file()
    assert task.overall()["done"] == 3


def test_concurrency_is_bounded(tmp_path):
    plan = _plan(tmp_path)
    settings = Settings(concurrency=2)
    manager = DownloadManager(settings)
    task = manager.create(plan, [i.item_id for i in plan.downloadable])
    fetcher = FakeFetcher()

    asyncio.run(manager.run(task, plan, fetcher))

    assert fetcher.peak <= 2


def test_retry_recovers_from_transient_failure(tmp_path):
    plan = _plan(tmp_path)
    settings = Settings(retries=3)
    manager = DownloadManager(settings)
    task = manager.create(plan, [i.item_id for i in plan.downloadable])
    fetcher = FakeFetcher(fail_times=1)

    asyncio.run(manager.run(task, plan, fetcher))

    assert task.state == "done"
    assert all(it.state is DownloadState.DONE for it in task.items)


def test_exhausted_retries_mark_failed(tmp_path):
    plan = _plan(tmp_path)
    settings = Settings(retries=1)
    manager = DownloadManager(settings)
    task = manager.create(plan, [i.item_id for i in plan.downloadable])
    fetcher = FakeFetcher(fail_times=99)

    asyncio.run(manager.run(task, plan, fetcher))

    assert task.state == "failed"
    assert all(it.state is DownloadState.FAILED for it in task.items)


def test_html_payload_is_rejected_and_quarantined(tmp_path):
    plan = _plan(tmp_path)
    settings = Settings(retries=1)
    manager = DownloadManager(settings)
    task = manager.create(plan, [i.item_id for i in plan.downloadable])
    fetcher = FakeFetcher(payload={"a.safetensors": b"<!doctype html><html>404</html>"})

    asyncio.run(manager.run(task, plan, fetcher))

    by_name = {it.filename: it for it in task.items}
    assert by_name["a.safetensors"].state is DownloadState.FAILED
    assert "HTML" in (by_name["a.safetensors"].error or "")
    lora_dir = tmp_path / "models" / "loras"
    assert not (lora_dir / "a.safetensors").exists()
    assert (lora_dir / "a.safetensors.corrupt").exists()


def test_already_present_items_are_skipped(tmp_path):
    root = _root(tmp_path)
    (root.models_dir / "loras" / "a.safetensors").write_bytes(make_safetensors(64))
    index = LocalIndex.build(root, ["loras", "vae"], health_check=True)
    plan = build_plan("j1", "wf.json", parse_workflow(WORKFLOW), index,
                      lambda c, f, r: ResolvedSource(
                          SourceKind.SEARCH, "org/x", f, len(make_safetensors(64)), score=0.9),
                      models_dir=str(root.models_dir))

    settings = Settings()
    manager = DownloadManager(settings)
    task = manager.create(plan)
    fetcher = FakeFetcher()

    asyncio.run(manager.run(task, plan, fetcher))

    assert "a.safetensors" not in fetcher.calls
    states = {it.filename: it.state for it in task.items}
    assert states["a.safetensors"] is DownloadState.SKIPPED
    assert states["b.safetensors"] is DownloadState.DONE


def test_unresolved_items_are_listed_not_downloaded(tmp_path):
    plan = _plan(tmp_path, sources={"a.safetensors": None, "b.safetensors": None,
                                    "c.safetensors": None})
    settings = Settings()
    manager = DownloadManager(settings)
    task = manager.create(plan, None)
    fetcher = FakeFetcher()

    asyncio.run(manager.run(task, plan, fetcher))

    assert fetcher.calls == []
    assert all(it.state is DownloadState.UNRESOLVED for it in task.items)


def test_cancel_stops_inflight(tmp_path):
    plan = _plan(tmp_path)
    settings = Settings(concurrency=1)
    manager = DownloadManager(settings)
    task = manager.create(plan, [i.item_id for i in plan.downloadable])
    fetcher = FakeFetcher()

    async def drive():
        run = asyncio.create_task(manager.run(task, plan, fetcher))
        await asyncio.sleep(0.02)
        task.cancel()
        await run

    asyncio.run(drive())

    assert task.cancelled
    assert task.state in {"cancelled", "failed"}


def test_history_and_lookup(tmp_path):
    plan = _plan(tmp_path)
    settings = Settings()
    manager = DownloadManager(settings)
    task = manager.create(plan, [i.item_id for i in plan.downloadable])
    asyncio.run(manager.run(task, plan, FakeFetcher()))

    assert manager.get(task.task_id) is task
    assert task.task_id in [t["task_id"] for t in manager.history()]
    payload = json.loads(json.dumps(task.to_dict(), ensure_ascii=False))
    assert payload["overall"]["total"] == 3
    assert payload["items"][0]["state"] == "done"
