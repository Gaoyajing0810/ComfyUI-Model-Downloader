"""FastAPI 后端：工作流上传 → 计划 → 下载 → 轮询进度。

JSON 契约见 README / web/app.js。本文件只做编排：解析与查重在 parser/scan，
来源匹配在 resolver + modelscope_client，下载执行在 downloader。
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.websockets import WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from . import __version__
from .cleanup import _AGE_SECONDS_DEFAULT, cleanup_stale_parts
from .config import Settings
from .downloader import DownloadManager
from .launcher import choose_folder, looks_like_comfyui
from .mapping import CATEGORY_DIRS
from .modelscope_client import ModelScopeIndex, build_route_fetcher
from .parser import WorkflowParseError, load_workflow
from .plan import Plan, ResolvedSource, SourceKind, build_plan
from .resolver import CuratedTable, Resolver
from .scan import ComfyRoot, LocalIndex, iter_model_files
from .verify import VerifyStatus, verify_file

WEB_DIR = Path(__file__).parent / "web"
_PLAN_MAX_BYTES: int = 50 * 1024 * 1024  # /api/plan 上传上限：典型 workflow <1MB；50MB 给异常大文件留余量
_PLANS: dict[str, Plan] = {}
_RUNNING: set[asyncio.Task[None]] = set()

#: 最近一次收到浏览器心跳的时刻（time.monotonic）。launcher 用它判断前台是否已关闭。
_heartbeat_ts: float = 0.0


def get_last_heartbeat() -> float:
    """最近一次心跳的时间戳（time.monotonic 基准），未被 ping 过则为 0。"""
    return _heartbeat_ts


def touch_heartbeat() -> None:
    global _heartbeat_ts
    _heartbeat_ts = time.monotonic()


#: 浏览器主动请求退出的生效时刻（time.monotonic 基准）；为 0 表示未请求。
#: ``request_shutdown()`` 设 ``time.monotonic() + _SHUTDOWN_GRACE_SECONDS``，
#: launcher 在该时刻之后才退服务，期间如果心跳到达（页面刷新后重连）就撤销。
#: 这避免了"刷新浏览器也触发 pagehide → 误杀"的 bug（pagehide 在 reload 和真关闭时都触发）。
_shutdown_requested_at: float = 0.0

#: 主动退出倒计时窗口（秒）。期间新心跳能撤销关闭请求，覆盖刷新页面场景。
_shutdown_grace_seconds: float = 5.0

#: /api/shutdown 的双因子：仅允许 loopback 调用 + 必须近期有心跳（秒）。
_shutdown_auth_window_seconds: float = 30.0
_shutdown_allowed_hosts: frozenset[str] = frozenset({"127.0.0.1", "::1", "testclient"})


def request_shutdown() -> None:
    """标记一次前端主动请求退出。launcher 在下个轮询周期读到后会让 server 优雅退出。"""
    global _shutdown_requested_at
    _shutdown_requested_at = time.monotonic() + _shutdown_grace_seconds


def cancel_shutdown_request() -> bool:
    """撤销最近一次主动退出请求（在 grace 窗口内）。新心跳连上时由 ws_heartbeat 调用。
    返回是否真的撤销了什么——仅在 grace 窗口内还有效的请求才会撤销（避免被旧的撤销信号意外复活）。"""
    global _shutdown_requested_at
    if _shutdown_requested_at <= 0:
        return False
    if time.monotonic() >= _shutdown_requested_at:
        return False  # 已超时，launcher 可能已经退出或正在退出，不复活
    _shutdown_requested_at = 0.0
    return True


class OverrideBody(BaseModel):
    job_id: str
    item_id: int
    repo_id: str = ""
    file_path: str = ""
    url: str = ""
    size: int | None = None
    sha256: str | None = None


class DownloadBody(BaseModel):
    job_id: str
    item_ids: list[int] | None = None


class VerifyBody(BaseModel):
    all: bool = True
    category: str | None = None
    deep: bool = False


class ConfigBody(BaseModel):
    comfy_root: str
    models_dir: str | None = None
    concurrency: int | None = None
    persist: bool = True


def _settings() -> Settings:
    return Settings.load()


def _models_root(settings: Settings) -> Path:
    if settings.models_dir is not None:
        return settings.models_dir
    if settings.comfy_root is not None:
        return settings.comfy_root / "models"
    raise HTTPException(400, "未配置 ComfyUI 模型目录：请设置环境变量 COMFY_ROOT 或 COMFY_MODELS_DIR")


def _root(settings: Settings) -> ComfyRoot:
    models = _models_root(settings)
    if not models.is_dir():
        raise HTTPException(400, f"模型目录不存在：{models}")
    return ComfyRoot.resolve(settings.comfy_root, models)


def _get_plan(job_id: str) -> Plan:
    plan = _PLANS.get(job_id)
    if plan is None:
        raise HTTPException(404, f"计划不存在或已过期：{job_id}")
    return plan


def _make_resolver(settings: Settings) -> Resolver:
    index = ModelScopeIndex(token=settings.token, timeout=settings.timeout)
    return Resolver(index, CuratedTable.load(settings.curated_path))


def _apply_comfy_root(st: Settings, raw: str, models_dir: str | None) -> tuple[Path, Path]:
    """校验并套用新的 ComfyUI 目录，返回 (根目录, 模型目录)。"""
    root = Path(raw).expanduser()
    if not root.is_absolute():
        raise HTTPException(400, "请填写绝对路径")
    root = root.resolve()
    if not root.is_dir():
        raise HTTPException(400, f"目录不存在：{root}")

    models = (Path(models_dir).expanduser().resolve() if models_dir else root / "models")
    if not models.is_dir():
        try:
            models.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HTTPException(400, f"无法创建模型目录 {models}：{exc}") from exc

    # 原地改写：所有端点都闭包引用同一个 st，改完立即对后续请求生效
    st.comfy_root = root
    st.models_dir = models
    return root, models


def _probe(root: Path, models: Path) -> dict[str, Any]:
    ok, notes = looks_like_comfyui(root)
    count = 0
    if models.is_dir():
        comfy = ComfyRoot.resolve(root, models)
        for category in CATEGORY_DIRS:
            count += sum(1 for _ in iter_model_files(comfy, category, health_check=False))
    return {
        "comfy_root": str(root),
        "models_dir": str(models),
        "looks_like_comfyui": ok,
        "notes": notes,
        "model_file_count": count,
    }


_DETECT_SEED_MAX_ITEMS: int = 30
_DETECT_TIMEOUT_SECONDS: float = 2.5
_DETECT_MAX_RESULTS: int = 20


def _scan_one_seed(seed: Path) -> list[str]:
    out: list[str] = []
    try:
        is_seed_dir = seed.is_dir()
    except OSError:
        return out
    if not is_seed_dir:
        return out
    if seed.name.lower().startswith("comfy"):
        candidates: list[Path] = [seed]
    else:
        try:
            candidates = list(seed.iterdir())
        except OSError:
            return out
        if len(candidates) > _DETECT_SEED_MAX_ITEMS:
            candidates = candidates[:_DETECT_SEED_MAX_ITEMS]
    for c in candidates:
        if c.name.startswith("."):
            continue
        try:
            if not c.is_dir():
                continue
            has_models = (c / "models").is_dir()
            has_comfy = (c / "comfy").is_dir()
        except OSError:
            continue
        if has_models and has_comfy:
            out.append(str(c))
    return out


def _detect_candidates() -> list[str]:
    home = Path.home()
    seeds = [home / n for n in ("ComfyUI", "comfyui", "comfy", "Documents", "Desktop", "Downloads")]
    seen: list[Path] = []
    seen_set: set[Path] = set()
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="detect-candidates") as ex:
        futures = {ex.submit(_scan_one_seed, s): s for s in seeds}
        try:
            for fut in as_completed(futures, timeout=_DETECT_TIMEOUT_SECONDS):
                try:
                    result = fut.result()
                except Exception:
                    continue
                for p in result:
                    pp = Path(p)
                    if pp in seen_set:
                        continue
                    seen_set.add(pp)
                    seen.append(pp)
                    if len(seen) >= _DETECT_MAX_RESULTS:
                        return [str(x) for x in seen[:_DETECT_MAX_RESULTS]]
        except TimeoutError:
            pass
    return [str(p) for p in seen[:_DETECT_MAX_RESULTS]]


async def _build_plan_async(
    settings: Settings, raw: bytes, name: str, job_id: str,
    resolve: bool, health_check: bool,
) -> Plan:
    root = _root(settings)
    try:
        parsed = await asyncio.to_thread(load_workflow, raw)
    except WorkflowParseError as exc:
        raise HTTPException(400, str(exc)) from exc

    categories = list(CATEGORY_DIRS)
    local = await asyncio.to_thread(LocalIndex.build, root, categories, health_check)

    if resolve:
        resolver = await asyncio.to_thread(_make_resolver, settings)
        plan = await asyncio.to_thread(
            build_plan, job_id, name, parsed, local,
            lambda category, filename, _ref: resolver.resolve(category, filename),
            str(root.models_dir), str(root.root or ""),
        )
    else:
        plan = build_plan(
            job_id, name, parsed, local, None,
            str(root.models_dir), str(root.root or ""),
        )
    return plan


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="ComfyUI Model Downloader", version=__version__)
    st = settings or _settings()
    manager = DownloadManager(st)
    fetcher = build_route_fetcher(token=st.token, timeout=st.timeout)

    @app.middleware("http")
    async def _limit_body(request, call_next):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > _PLAN_MAX_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": f"请求体超过 {_PLAN_MAX_BYTES // (1024 * 1024)}MB 上限"},
            )
        return await call_next(request)

    if st.models_dir:
        try:
            removed = cleanup_stale_parts(Path(st.models_dir), max_age_seconds=_AGE_SECONDS_DEFAULT)
            if removed:
                import logging
                logging.getLogger(__name__).info("启动清理 %d 个陈旧 .part 残骸", removed)
        except Exception:  # noqa: BLE001
            pass

    @app.get("/api/config")
    async def get_config() -> dict[str, Any]:
        return {
            **st.to_dict(),
            "version": __version__,
            "categories": list(CATEGORY_DIRS),
            "web_dir_exists": WEB_DIR.is_dir(),
        }

    @app.post("/api/config")
    async def post_config(body: ConfigBody) -> dict[str, Any]:
        root, models = _apply_comfy_root(st, body.comfy_root, body.models_dir)
        if body.concurrency is not None:
            if not 1 <= body.concurrency <= 16:
                raise HTTPException(400, "并发数需在 1–16 之间")
            st.concurrency = body.concurrency
        if body.persist:
            try:
                st.save()
            except OSError as exc:
                raise HTTPException(500, f"配置保存失败：{exc}") from exc
        return {**await get_config(), "saved": body.persist, "probe": _probe(root, models)}

    @app.post("/api/config/browse")
    async def post_browse() -> dict[str, Any]:
        chosen = await asyncio.to_thread(choose_folder, "选择 ComfyUI 根目录", "请选择包含 models 目录的 ComfyUI 文件夹")
        if chosen is None:
            return {"path": None, "supported": sys.platform == "darwin"}
        root, models = _apply_comfy_root(st, chosen, None)
        return {"path": str(root), "supported": True, "probe": _probe(root, models)}

    @app.post("/api/config/detect")
    async def post_detect() -> dict[str, Any]:
        candidates = await asyncio.to_thread(_detect_candidates)
        return {"candidates": candidates, "current": str(st.comfy_root) if st.comfy_root else None}

    @app.post("/api/plan")
    async def post_plan(
        file: UploadFile = File(...),
        resolve: bool = Query(True, description="是否联网匹配魔搭来源"),
        health_check: bool = Query(False, description="是否体检本地已有模型文件"),
    ) -> dict[str, Any]:
        raw = await file.read()
        if not raw:
            raise HTTPException(400, "上传的文件为空")
        if len(raw) > _PLAN_MAX_BYTES:
            raise HTTPException(
                413,
                f"上传内容超过 {_PLAN_MAX_BYTES // (1024 * 1024)}MB 上限",
            )
        job_id = f"j_{int(time.time() * 1000) & 0xFFFFFF:06x}"
        name = Path(file.filename or "workflow.json").name
        plan = await _build_plan_async(st, raw, name, job_id, resolve, health_check)
        _PLANS[job_id] = plan
        if len(_PLANS) > 50:
            for stale in list(_PLANS)[:-50]:
                _PLANS.pop(stale, None)
        return plan.to_dict()

    @app.post("/api/plan/override")
    async def post_override(body: OverrideBody) -> dict[str, Any]:
        plan = _get_plan(body.job_id)
        item = plan.by_id(body.item_id)
        if item is None:
            raise HTTPException(404, f"计划项不存在：{body.item_id}")
        is_url = bool(body.url)
        if not is_url and (not body.repo_id or not body.file_path):
            raise HTTPException(400, "需要同时提供 repo_id + file_path，或粘贴直连 URL")

        size, sha256 = body.size, body.sha256
        detail = ""
        if is_url:
            kind = SourceKind.URL
            url = body.url.strip()
            if not (url.startswith("https://") or url.startswith("http://")):
                raise HTTPException(400, f"URL 必须以 http(s) 开头：{url}")
            new_source = ResolvedSource(
                kind=kind, repo_id="", file_path="", url=url,
                size=size, sha256=sha256, score=1.0,
            )
            note_extra = "（直连 URL，未自动校验元数据）"
        else:
            kind = SourceKind.OVERRIDE
            if size is None or sha256 is None:
                try:
                    found = await asyncio.to_thread(
                        ModelScopeIndex(token=st.token, timeout=st.timeout).find_file,
                        body.repo_id, body.file_path,
                    )
                except Exception as exc:  # noqa: BLE001 元数据缺失不阻断人工指定
                    found = None
                    detail = f"（无法读取仓库元数据：{exc}）"
                else:
                    detail = ""
                if found is not None:
                    size = size if size is not None else found.size
                    sha256 = sha256 or found.sha256
            new_source = ResolvedSource(
                kind=kind,
                repo_id=body.repo_id,
                file_path=body.file_path,
                size=size,
                sha256=sha256,
                score=1.0,
            )
            note_extra = ""

        item.source = new_source
        item.selected = not item.local.exists
        return {
            **plan.to_dict(),
            "item": item.to_dict(),
            "note": (detail or "已采用人工指定的来源") + note_extra,
        }

    @app.post("/api/download")
    async def post_download(body: DownloadBody) -> dict[str, Any]:
        plan = _get_plan(body.job_id)
        if not plan.downloadable:
            raise HTTPException(400, "没有需要下载的模型：要么已全部存在，要么来源未确认")
        task = manager.create(plan, body.item_ids)
        runner = asyncio.create_task(manager.run(task, plan, fetcher))
        _RUNNING.add(runner)

        def _on_runner_done(t: asyncio.Task) -> None:
            _RUNNING.discard(t)
            exc = t.exception()
            if exc is not None:
                logging.getLogger(__name__).exception(
                    "download runner task %s crashed", task.task_id, exc_info=exc
                )
                if task.state == "running":
                    task.state = "failed"
                    task.log(f"runner task 异常: {type(exc).__name__}: {exc}")

        runner.add_done_callback(_on_runner_done)
        return {"task_id": task.task_id}

    @app.get("/api/progress/{task_id}")
    async def get_progress(task_id: str) -> dict[str, Any]:
        task = manager.get(task_id)
        if task is None:
            raise HTTPException(404, f"任务不存在：{task_id}")
        return task.to_dict()

    @app.post("/api/task/{task_id}/cancel")
    async def post_cancel(task_id: str) -> dict[str, Any]:
        task = manager.get(task_id)
        if task is None:
            raise HTTPException(404, f"任务不存在：{task_id}")
        task.cancel()
        return {"ok": True, "task_id": task_id}

    @app.get("/api/history")
    async def get_history() -> dict[str, Any]:
        return {"tasks": manager.history()}

    @app.get("/api/logs")
    async def get_logs(task_id: str = Query(...)) -> dict[str, Any]:
        return {"lines": manager.logs(task_id)}

    @app.post("/api/verify")
    async def post_verify(body: VerifyBody) -> dict[str, Any]:
        root = _root(st)
        categories = [body.category] if body.category else list(CATEGORY_DIRS)
        if body.category and body.category not in CATEGORY_DIRS:
            raise HTTPException(400, f"未知模型类别：{body.category}")

        def _scan() -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            for category in categories:
                for path in iter_model_files(root, category):
                    result = verify_file(
                        path, deep=body.deep,
                        expected_size=path.stat().st_size,
                    )
                    out.append({
                        "path": str(path),
                        "category": category,
                        "status": result.status.value,
                        "ok": result.status in (VerifyStatus.OK, VerifyStatus.NO_CHECKSUM),
                        "size": result.size,
                        "detail": result.detail,
                    })
            return out

        items = await asyncio.to_thread(_scan)
        return {
            "items": items,
            "totals": {
                "total": len(items),
                "ok": sum(1 for i in items if i["ok"]),
                "bad": sum(1 for i in items if not i["ok"]),
            },
        }

    @app.exception_handler(Exception)
    async def on_error(_request: Any, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": f"服务器内部错误：{exc}"})

    @app.websocket("/ws/heartbeat")
    async def ws_heartbeat(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                await websocket.receive_text()
                touch_heartbeat()
                cancel_shutdown_request()  # 任何心跳都撤销 pagehide 倒计时（覆盖刷新场景）
        except WebSocketDisconnect:
            pass

    @app.post("/api/shutdown")
    async def post_shutdown(request: Request) -> dict[str, bool]:
        client_host = (request.client.host if request.client else "")
        if client_host not in _shutdown_allowed_hosts:
            raise HTTPException(403, f"shutdown 仅允许 loopback 调用（当前 {client_host!r}）")
        if time.monotonic() - _heartbeat_ts > _shutdown_auth_window_seconds:
            raise HTTPException(403, "shutdown 拒绝：近 30s 内未收到心跳")
        request_shutdown()
        return {"ok": True}

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    else:

        @app.get("/")
        async def web_missing() -> dict[str, Any]:
            return {"detail": "Web 界面文件缺失（comfy_model_downloader/web/）", "api": "/docs"}

    return app


app = create_app()


def main() -> None:  # pragma: no cover - 入口
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765)


__all__ = ["create_app", "app", "main"]
