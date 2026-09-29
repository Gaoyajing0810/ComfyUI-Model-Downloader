"""modelscope_client 离线单测：用 httpx.MockTransport 拦截全部请求，不访问网络。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from comfy_model_downloader.modelscope_client import (
    ModelScopeError,
    ModelScopeFetcher,
    ModelScopeIndex,
    _total_from,
)
from comfy_model_downloader.plan import ResolvedSource, SourceKind

DOLPHIN_OK = {
    "Code": 200,
    "Data": {
        "Model": {
            "Models": [
                {
                    "Name": "Realistic_Vision_V5.1_noVAE",
                    "Path": "AI-ModelScope",
                    "ChineseName": "真实感视觉5.1",
                    "Downloads": 123456,
                    "Stars": 88,
                    "Visibility": "public",
                },
                {
                    "Name": "无关仓库",
                    "Path": "somebody",
                    "Downloads": 1,
                    "Stars": 0,
                    "Visibility": "public",
                },
            ]
        }
    },
}


def _json_response(payload: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def _make_index(transport: httpx.MockTransport) -> ModelScopeIndex:
    return ModelScopeIndex(token="secret-token", transport=transport)


def test_dolphin_search_拼接repo_id并按名称打分() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return _json_response(DOLPHIN_OK)

    index = _make_index(httpx.MockTransport(handler))
    results = index.search("Realistic_Vision_V5.1.safetensors", category="checkpoints", limit=5)

    assert results[0].repo_id == "AI-ModelScope/Realistic_Vision_V5.1_noVAE"
    assert results[0].score > 0.8
    assert all(c.repo_id != "somebody/无关仓库" or c.score < results[0].score for c in results)
    assert seen[0].method == "PUT"
    assert seen[0].headers["authorization"] == "Bearer secret-token"


def test_dolphin_搜索词写入请求体() -> None:
    bodies: list[bytes] = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(req.content)
        return _json_response(DOLPHIN_OK)

    index = _make_index(httpx.MockTransport(handler))
    index.search("dreamshaper 8", category="checkpoints", limit=3)
    assert json.loads(bodies[0])["Name"] == "dreamshaper 8"
    assert json.loads(bodies[0])["PageSize"] >= 20


def test_dolphin_失败时降级到openapi() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/dolphin/models"):
            return httpx.Response(500)
        assert "/openapi/v1/models" in str(req.url)
        return _json_response(
            {
                "success": True,
                "data": {
                    "models": [
                        {"id": "MusePublic/FLUX", "downloads": 999, "likes": 5},
                        {"id": "other/nope", "downloads": 0, "likes": 0},
                    ]
                },
            }
        )

    index = _make_index(httpx.MockTransport(handler))
    index._api = type("Stub", (), {
        "list_repos": staticmethod(lambda *a, **k: type(
            "P", (), {"items": [
                type("R", (), {"repo_id": "MusePublic/FLUX", "downloads": 999, "likes": 5})(),
                type("R", (), {"repo_id": "other/nope", "downloads": 0, "likes": 0})(),
            ]})())
    })()

    results = index.search("FLUX", category="diffusion_models", limit=5)
    assert results[0].repo_id == "MusePublic/FLUX"
    assert results[0].score > 0


def test_dolphin_全失败时返回空列表而非抛异常() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    index = _make_index(httpx.MockTransport(handler))
    index._api = type("Stub", (), {"list_repos": staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")))})()
    assert index.search("anything", category="checkpoints", limit=3) == []


def test_私有仓库被过滤() -> None:
    payload = {"Data": {"Model": {"Models": [
        {"Name": "secret", "Path": "me", "Visibility": "private", "Downloads": 10**6},
        {"Name": "open", "Path": "me", "Visibility": "public", "Downloads": 1},
    ]}}}
    index = _make_index(httpx.MockTransport(lambda r: _json_response(payload)))
    assert [c.repo_id for c in index.search("secret", category="checkpoints", limit=5)] == ["me/open"]


def test_list_files_过滤tree并缓存() -> None:
    calls: list[str] = []

    class FakeInfo:
        def __init__(self, path: str, is_dir: bool, size: int, sha: str) -> None:
            self.path, self.is_dir, self.size, self.sha256 = path, is_dir, size, sha
            self.name = path.rsplit("/", 1)[-1]

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return _json_response({"Data": {"Files": []}})

    index = _make_index(httpx.MockTransport(handler))
    index._api = type("Stub", (), {"list_repo_files": staticmethod(
        lambda repo_id, repo_type: (
            calls.append(repo_id),
            [
                FakeInfo("flux1-dev.safetensors", False, 23579431568, "a" * 64),
                FakeInfo("subdir", True, 0, ""),
                FakeInfo("README.md", False, 100, "b" * 64),
            ],
        )[1]
    )})()

    files = index.list_files("AI-ModelScope/FLUX.1-dev")
    assert [f.path for f in files] == ["flux1-dev.safetensors", "README.md"]
    assert files[0].size == 23579431568
    assert files[0].sha256 == "a" * 64

    index.list_files("AI-ModelScope/FLUX.1-dev")
    assert calls.count("AI-ModelScope/FLUX.1-dev") == 1  # 第二次走缓存


def test_find_file_全路径与basename都能命中() -> None:
    class FakeInfo:
        def __init__(self, path: str) -> None:
            self.path, self.is_dir, self.size, self.sha256 = path, False, 1, "c" * 64
            self.name = path.rsplit("/", 1)[-1]

    index = ModelScopeIndex()
    index._api = type("Stub", (), {"list_repo_files": staticmethod(
        lambda *a, **k: [FakeInfo("ae.safetensors")])})()
    assert index.find_file("o/r", "ae.safetensors") is not None
    assert index.find_file("o/r", "missing.safetensors") is None


def test_find_file_仓库取不到时抛ModelScopeError() -> None:
    index = ModelScopeIndex()
    index._api = type("Stub", (), {"list_repo_files": staticmethod(
        lambda *a, **k: (_ for _ in ()).throw(ValueError("404")))})()
    with pytest.raises(ModelScopeError, match="读取仓库文件列表失败"):
        index.find_file("bad/repo", "x.safetensors")


# ------------------------------------------------------------------ Fetcher


def _source(repo_id: str = "AI-ModelScope/FLUX.1-dev", file_path: str = "flux1-dev.safetensors") -> ResolvedSource:
    return ResolvedSource(
        kind=SourceKind.SEARCH,
        repo_id=repo_id,
        file_path=file_path,
        size=len(b"x" * 8),
        sha256="d" * 64,
    )


def test_302两段式_第二段不带鉴权头(tmp_path) -> None:
    seen: list[httpx.Request] = []
    payload = b"MODELBYTES" * 100

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if "modelscope.cn" in req.url.host:
            return httpx.Response(302, headers={"location": "https://cdn.example.com/obj?auth_key=xyz"})
        return httpx.Response(200, content=payload, headers={"content-length": str(len(payload))})

    fetcher = ModelScopeFetcher(token="secret-token", transport=httpx.MockTransport(handler))
    dest = tmp_path / "unet" / "m.safetensors"
    seen_progress: list[tuple[int, int]] = []

    meta = asyncio.run(fetcher.fetch(_source(), dest, on_progress=lambda d, t: seen_progress.append((d, t))))

    assert len(seen) == 2
    assert seen[0].headers["authorization"] == "Bearer secret-token"
    assert "authorization" not in {k.lower() for k in seen[1].headers}
    assert "cookie" not in {k.lower() for k in seen[1].headers}
    assert dest.read_bytes() == payload
    assert not dest.with_name(dest.name + ".part").exists()
    assert meta["size"] == len(payload)
    assert seen_progress[-1] == (len(payload), len(payload))


def test_断点续传_206追加写入(tmp_path) -> None:
    seen: list[httpx.Request] = []
    dest = tmp_path / "m.safetensors"
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(b"HEAD")
    tail = b"TAIL"

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if "modelscope.cn" in req.url.host:
            return httpx.Response(302, headers={"location": "https://cdn.example.com/obj"})
        return httpx.Response(
            206,
            content=tail,
            headers={"content-range": f"bytes 4-{4 + len(tail) - 1}/8"},
        )

    fetcher = ModelScopeFetcher(transport=httpx.MockTransport(handler))
    asyncio.run(fetcher.fetch(_source(), dest))

    assert seen[-1].headers["range"] == "bytes=4-"
    assert dest.read_bytes() == b"HEADTAIL"
    assert not part.exists()


def test_服务端忽略Range时截断重写(tmp_path) -> None:
    dest = tmp_path / "m.safetensors"
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(b"STALE")

    def handler(req: httpx.Request) -> httpx.Response:
        if "modelscope.cn" in req.url.host:
            return httpx.Response(302, headers={"location": "https://cdn.example.com/obj"})
        return httpx.Response(200, content=b"FRESH", headers={"content-length": "5"})

    fetcher = ModelScopeFetcher(transport=httpx.MockTransport(handler))
    asyncio.run(fetcher.fetch(_source(), dest))
    assert dest.read_bytes() == b"FRESH"


def test_416视为已完成直接收尾(tmp_path) -> None:
    dest = tmp_path / "m.safetensors"
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(b"COMPLETE")

    def handler(req: httpx.Request) -> httpx.Response:
        if "modelscope.cn" in req.url.host:
            return httpx.Response(302, headers={"location": "https://cdn.example.com/obj"})
        return httpx.Response(416)

    fetcher = ModelScopeFetcher(transport=httpx.MockTransport(handler))
    asyncio.run(fetcher.fetch(_source(), dest))
    assert dest.read_bytes() == b"COMPLETE"
    assert not part.exists()


def test_中途取消抛CancelledError并保留part(tmp_path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "modelscope.cn" in req.url.host:
            return httpx.Response(302, headers={"location": "https://cdn.example.com/obj"})
        return httpx.Response(200, content=b"y" * 5000, headers={"content-length": "5000"})

    dest = tmp_path / "m.safetensors"
    part = dest.with_name(dest.name + ".part")
    fetcher = ModelScopeFetcher(chunk=100, transport=httpx.MockTransport(handler))

    calls = {"n": 0}

    def cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(fetcher.fetch(_source(), dest, should_cancel=cancel))
    assert part.exists() and not dest.exists()


def test_缺少repo_id时直接报错(tmp_path) -> None:
    fetcher = ModelScopeFetcher(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(ModelScopeError, match="来源缺少"):
        asyncio.run(fetcher.fetch(ResolvedSource(kind=SourceKind.NONE), tmp_path / "x.safetensors"))


def test_HTTP错误状态给出可读中文错误(tmp_path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if "modelscope.cn" in req.url.host:
            return httpx.Response(404)
        raise AssertionError("不应走到 CDN")

    fetcher = ModelScopeFetcher(transport=httpx.MockTransport(handler))
    with pytest.raises(ModelScopeError, match="HTTP 404"):
        asyncio.run(fetcher.fetch(_source(), tmp_path / "x.safetensors"))


def test_重定向缺少Location时报错(tmp_path) -> None:
    fetcher = ModelScopeFetcher(transport=httpx.MockTransport(lambda r: httpx.Response(302)))
    with pytest.raises(ModelScopeError, match="缺少 Location"):
        asyncio.run(fetcher.fetch(_source(), tmp_path / "x.safetensors"))


def test_非LFS文件走同源直取(tmp_path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert "modelscope.cn" in req.url.host
        return httpx.Response(200, content=b"version: 0.4\n", headers={"content-length": "13"})

    fetcher = ModelScopeFetcher(token="t", transport=httpx.MockTransport(handler))
    dest = tmp_path / "config.yaml"
    asyncio.run(fetcher.fetch(_source(file_path="config.yaml"), dest))
    assert dest.read_bytes() == b"version: 0.4\n"


def test_total_from_优先级(tmp_path) -> None:
    def resp(headers: dict[str, str]) -> httpx.Response:
        return httpx.Response(200, headers=headers)

    assert _total_from(resp({"content-range": "bytes 0-9/1000"}), 0) == 1000
    assert _total_from(resp({"content-range": "bytes 100-199/1000", "content-length": "100"}), 100) == 1000
    assert _total_from(resp({"content-length": "500"}), 100) == 600
    assert _total_from(resp({}), 0) == 0


def test_env_endpoint可覆盖() -> None:
    import comfy_model_downloader.modelscope_client as msc

    msc.os.environ["MODELSCOPE_ENDPOINT"] = "https://mirror.example.com/"
    try:
        assert msc._endpoint() == "https://mirror.example.com"
    finally:
        del msc.os.environ["MODELSCOPE_ENDPOINT"]


def test_无token时不发鉴权头(tmp_path) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if "modelscope.cn" in req.url.host:
            return httpx.Response(302, headers={"location": "https://cdn.example.com/o"})
        return httpx.Response(200, content=b"z", headers={"content-length": "1"})

    fetcher = ModelScopeFetcher(transport=httpx.MockTransport(handler))
    fetcher._token = None
    asyncio.run(fetcher.fetch(_source(), tmp_path / "x.safetensors"))
    assert "authorization" not in {k.lower() for k in seen[0].headers}
