"""server.py 的离线测试：用 TestClient 打全部端点，不联网、不落真实大文件。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comfy_model_downloader.config import Settings  # noqa: E402
from comfy_model_downloader.server import create_app  # noqa: E402
from comfy_model_downloader import server as server_mod  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "flux_workflow_ui.json"


def _safetensors(payload: bytes) -> bytes:
    header = json.dumps({"x": {"dtype": "F32", "shape": [len(payload) // 4], "data_offsets": [0, len(payload)]}}).encode()
    return len(header).to_bytes(8, "little") + header + payload


@pytest.fixture()
def comfy_root(tmp_path: Path) -> Path:
    models = tmp_path / "models"
    (models / "loras").mkdir(parents=True)
    (models / "loras" / "flux-detail-sldr-b1.safetensors").write_bytes(_safetensors(b"\x00" * 64))
    (models / "unet").mkdir(parents=True)
    (models / "unet" / "broken.safetensors").write_bytes(b"<html>error page</html>")
    return tmp_path


@pytest.fixture()
def client(comfy_root: Path) -> TestClient:
    settings = Settings(comfy_root=comfy_root, deep_verify=True)
    server_mod._PLANS.clear()
    return TestClient(create_app(settings))


def _upload(client: TestClient, resolve: str = "false"):
    raw = FIXTURE.read_bytes()
    return client.post(
        "/api/plan",
        files={"file": ("flux.json", raw, "application/json")},
        params={"resolve": resolve, "health_check": "true"},
    )


def test_config_reports_paths(client: TestClient, comfy_root: Path) -> None:
    body = client.get("/api/config").json()
    assert body["models_dir"] == str(comfy_root / "models")
    assert body["comfy_root"] == str(comfy_root)
    # 版本号由 scripts/bump_version.py 维护；只断言格式是 X.Y.Z，不绑定具体数字。
    assert re.match(r"^\d+\.\d+\.\d+", body["version"]), body["version"]
    assert "checkpoints" in body["categories"]


def test_plan_parses_workflow_and_marks_local(client: TestClient) -> None:
    resp = _upload(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["workflow_name"] == "flux.json"
    assert body["parse"]["format"] == "ui"
    assert body["parse"]["nodes_scanned"] == 11
    assert len(body["items"]) == 8

    by_name = {i["filename"]: i for i in body["items"]}
    assert by_name["flux-detail-sldr-b1.safetensors"]["local"]["status"] == "exact"
    assert by_name["flux1-dev.safetensors"]["category_dir"] == "unet"
    assert by_name["CLIP-ViT-H-14-laion2B-s32E-b79K.safetensors"]["category"] == "clip_vision"
    assert body["totals"]["present"] == 1
    assert body["totals"]["unresolved"] == 7


def test_plan_rejects_non_json(client: TestClient) -> None:
    resp = client.post(
        "/api/plan", files={"file": ("x.json", b"not a workflow", "application/json")}
    )
    assert resp.status_code == 400
    assert "JSON" in resp.json()["detail"]


def test_plan_rejects_empty_upload(client: TestClient) -> None:
    resp = client.post("/api/plan", files={"file": ("x.json", b"", "application/json")})
    assert resp.status_code == 400


def test_download_rejected_when_nothing_resolved(client: TestClient) -> None:
    job_id = _upload(client).json()["job_id"]
    resp = client.post("/api/download", json={"job_id": job_id})
    assert resp.status_code == 400
    assert "没有需要下载" in resp.json()["detail"]


def test_download_404_on_unknown_job(client: TestClient) -> None:
    assert client.post("/api/download", json={"job_id": "nope"}).status_code == 404


def test_override_404_and_400(client: TestClient) -> None:
    job_id = _upload(client).json()["job_id"]
    assert client.post(
        "/api/plan/override", json={"job_id": "nope", "item_id": 1, "repo_id": "a/b", "file_path": "f"}
    ).status_code == 404

    resp = client.post(
        "/api/plan/override", json={"job_id": job_id, "item_id": 999, "repo_id": "a/b", "file_path": "f"}
    )
    assert resp.status_code == 404

    resp = client.post(
        "/api/plan/override", json={"job_id": job_id, "item_id": 1, "repo_id": "", "file_path": ""}
    )
    assert resp.status_code == 400


def test_override_marks_item_downloadable(client: TestClient) -> None:
    body = _upload(client).json()
    target = next(i for i in body["items"] if i["filename"] == "flux1-dev.safetensors")
    resp = client.post(
        "/api/plan/override",
        json={
            "job_id": body["job_id"],
            "item_id": target["id"],
            "repo_id": "AI-ModelScope/FLUX.1-dev",
            "file_path": "flux1-dev.safetensors",
            "size": 23579431568,
            "sha256": "a" * 64,
        },
    )
    assert resp.status_code == 200
    out = resp.json()
    assert out["item"]["source"]["kind"] == "override"
    assert out["item"]["source"]["repo_id"] == "AI-ModelScope/FLUX.1-dev"
    assert out["item"]["needs_download"] is True
    assert out["totals"]["to_download"] == 1
    assert out["totals"]["bytes_to_download"] == 23579431568


def test_override_then_download_starts_task(client: TestClient) -> None:
    body = _upload(client).json()
    target = next(i for i in body["items"] if i["filename"] == "flux1-dev.safetensors")
    client.post(
        "/api/plan/override",
        json={
            "job_id": body["job_id"], "item_id": target["id"],
            "repo_id": "AI-ModelScope/FLUX.1-dev", "file_path": "flux1-dev.safetensors",
            "size": 64, "sha256": "b" * 64,
        },
    )
    resp = client.post("/api/download", json={"job_id": body["job_id"]})
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]
    assert client.get(f"/api/progress/{task_id}").status_code == 200
    assert client.get("/api/history").json()["tasks"][0]["task_id"] == task_id
    assert isinstance(client.get("/api/logs", params={"task_id": task_id}).json()["lines"], list)


def test_progress_and_cancel_404(client: TestClient) -> None:
    assert client.get("/api/progress/nope").status_code == 404
    assert client.post("/api/task/nope/cancel").status_code == 404
    assert client.get("/api/logs", params={"task_id": "nope"}).json() == {"lines": []}


def test_verify_finds_corrupt_file(client: TestClient) -> None:
    body = client.post("/api/verify", json={"all": True}).json()
    assert body["totals"]["total"] == 2
    bad = [i for i in body["items"] if not i["ok"]]
    assert len(bad) == 1
    assert bad[0]["path"].endswith("unet/broken.safetensors")
    assert bad[0]["status"] == "not_a_model"


def test_verify_rejects_unknown_category(client: TestClient) -> None:
    resp = client.post("/api/verify", json={"all": False, "category": "not_a_category"})
    assert resp.status_code == 400


# —— 关前台退后台（双路径：主动 + 30 分钟兜底）的 grace + cancel 单测 ——

import time as _time


@pytest.fixture(autouse=True)
def _reset_shutdown_flag():
    """重置模块级 shutdown deadline（模块全局，跨 TestClient 不隔离）。"""
    server_mod._shutdown_requested_at = 0.0
    yield
    server_mod._shutdown_requested_at = 0.0


def test_request_shutdown_sets_deadline_in_grace_window(client: TestClient) -> None:
    before = _time.monotonic()
    resp = client.post("/api/shutdown")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    after = _time.monotonic()
    deadline = server_mod._shutdown_requested_at
    assert deadline > 0
    assert before + server_mod._shutdown_grace_seconds <= deadline <= after + server_mod._shutdown_grace_seconds


def test_cancel_resets_deadline(client: TestClient) -> None:
    client.post("/api/shutdown")
    assert server_mod._shutdown_requested_at > 0
    cancelled = server_mod.cancel_shutdown_request()
    assert cancelled is True
    assert server_mod._shutdown_requested_at == 0.0


def test_cancel_returns_false_when_no_pending_request() -> None:
    assert server_mod.cancel_shutdown_request() is False


def test_cancel_returns_false_after_deadline_passed() -> None:
    """已超时的 shutdown 请求不能被新 heartbeat 撤销（launcher 可能正在退出中，不能复活）。"""
    server_mod._shutdown_requested_at = _time.monotonic() - 1.0
    assert server_mod.cancel_shutdown_request() is False
    # 注意：deadline 不应被重置回 0 —— 留给 launcher 自然退出
    assert server_mod._shutdown_requested_at < _time.monotonic()


def test_ws_heartbeat_cancels_pending_shutdown(client: TestClient) -> None:
    """刷新场景核心：pagehide 发 shutdown → 5s 内新页面连 WS → cancel 撤销。"""
    client.post("/api/shutdown")
    assert server_mod._shutdown_requested_at > 0
    with client.websocket_connect("/ws/heartbeat") as ws:
        ws.send_text("ping")
    assert server_mod._shutdown_requested_at == 0.0


def test_launcher_check_logic_with_grace(client: TestClient) -> None:
    """验证 launcher 的判定逻辑与 server 的 grace 窗口一致（防止回归）。"""
    assert not (server_mod._shutdown_requested_at > 0 and _time.monotonic() >= server_mod._shutdown_requested_at)
    client.post("/api/shutdown")
    assert not (_time.monotonic() >= server_mod._shutdown_requested_at)
    server_mod._shutdown_requested_at = _time.monotonic() - 1.0
    assert _time.monotonic() >= server_mod._shutdown_requested_at
