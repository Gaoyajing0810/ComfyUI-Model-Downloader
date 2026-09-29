"""DirectURLFetcher 单测 + RouteFetcher 单测：httpx MockTransport 离线覆盖。

覆盖：
- 正常 GET 落盘（200 + content）+ 头不带 Authorization（无 token）
- 带 token → Authorization: Bearer 头
- 401 → ModelScopeError
- 416 → 视为完成、rename 落盘
- 206 Range 续传：先有 .part → 追加
- 200 不带 Range：offset>0 时截断重写
- 取消 → asyncio.CancelledError，.part 保留
- source 缺 url → ModelScopeError
- URL 非 http/https → ModelScopeError
- RouteFetcher 按 source.kind 分发到 ModelScopeFetcher / DirectURLFetcher
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest

from comfy_model_downloader.modelscope_client import (
    DirectURLFetcher,
    ModelScopeFetcher,
    RouteFetcher,
    build_route_fetcher,
    build_url_fetcher,
)
from comfy_model_downloader.plan import ResolvedSource, SourceKind


# —— 工具 ——

def _src(url: str = "", **kw) -> ResolvedSource:
    """构造 URL 来源（其他位置参数用默认）。"""
    return ResolvedSource(SourceKind.URL, url=url, **kw)


def _make_transport(handler):
    return httpx.MockTransport(handler)


def _ok_handler(body: bytes = b"HELLO", *, total: int | None = None,
                accept_ranges: bool = True, content_range: bool = True,
                chunked: bool = False) -> Any:
    """200/206 通用 handler：默认返回 body；total=None 时让 httpx 自填 content-length。"""
    total = total if total is not None else len(body)

    def handle(req: httpx.Request) -> httpx.Response:
        # 处理 Range 头
        range_h = req.headers.get("range")
        start = 0
        if range_h and range_h.startswith("bytes="):
            try:
                start = int(range_h[len("bytes="):].split("-", 1)[0])
            except ValueError:
                start = 0
        end = total
        status = 206 if range_h else 200
        sliced = body[start:end]
        headers: dict[str, str] = {}
        if accept_ranges:
            headers["accept-ranges"] = "bytes"
        if content_range and status == 206:
            headers["content-range"] = f"bytes {start}-{start + len(sliced) - 1}/{total}"
        return httpx.Response(status, content=sliced, headers=headers)

    return handle


# —— 正常路径 ——

@pytest.mark.asyncio
async def test_direct_url_basic_download(tmp_path: Path) -> None:
    body = b"X" * 4096
    fetcher = DirectURLFetcher(transport=_make_transport(_ok_handler(body)))
    dest = tmp_path / "model.safetensors"
    src = _src(url="https://example.com/m.safetensors")
    meta = await fetcher.fetch(src, dest, on_progress=None, should_cancel=lambda: False)
    assert dest.exists()
    assert dest.read_bytes() == body
    assert meta["size"] == len(body)
    assert not (dest.with_suffix(dest.suffix + ".part")).exists()


@pytest.mark.asyncio
async def test_direct_url_carries_authorization_when_token(tmp_path: Path) -> None:
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, content=b"OK")

    fetcher = DirectURLFetcher(token="tok-xyz", transport=_make_transport(handler))
    src = _src(url="https://example.com/x.safetensors")
    await fetcher.fetch(src, tmp_path / "x.safetensors")
    assert len(captured) == 1
    assert captured[0].headers.get("authorization") == "Bearer tok-xyz"


@pytest.mark.asyncio
async def test_direct_url_no_authorization_without_token(tmp_path: Path, monkeypatch) -> None:
    # 防止环境变量意外注入 token
    monkeypatch.delenv("DIRECT_URL_TOKEN", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("CIVITAI_TOKEN", raising=False)

    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, content=b"OK")

    fetcher = DirectURLFetcher(transport=_make_transport(handler))
    src = _src(url="https://example.com/x.safetensors")
    await fetcher.fetch(src, tmp_path / "x.safetensors")
    assert "authorization" not in captured[0].headers


# —— 错误路径 ——

@pytest.mark.asyncio
async def test_direct_url_401_raises(tmp_path: Path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Unauthorized")

    fetcher = DirectURLFetcher(transport=_make_transport(handler))
    src = _src(url="https://example.com/x.safetensors")
    from comfy_model_downloader.modelscope_client import ModelScopeError
    with pytest.raises(ModelScopeError, match="HTTP 401"):
        await fetcher.fetch(src, tmp_path / "x.safetensors")


@pytest.mark.asyncio
async def test_direct_url_416_treated_as_complete(tmp_path: Path) -> None:
    """已有 .part 文件 → Range 头发出 → 416 → 视为完成，rename 到 dest。"""
    dest = tmp_path / "x.safetensors"
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(b"existing-bytes")  # 13 bytes

    def handler(req: httpx.Request) -> httpx.Response:
        # 模拟服务端认为该 Range 已经超出（典型：客户端的 .part 已经比实际文件大）
        return httpx.Response(416)

    fetcher = DirectURLFetcher(transport=_make_transport(handler))
    src = _src(url="https://example.com/x.safetensors")
    meta = await fetcher.fetch(src, dest)
    # 416 路径：把已有 .part 内容当作已下载字节，rename 落盘
    assert dest.exists()
    assert dest.read_bytes() == b"existing-bytes"
    assert not part.exists()
    assert meta["size"] == len(b"existing-bytes")


# —— 断点续传 ——

@pytest.mark.asyncio
async def test_direct_url_range_resume_appends(tmp_path: Path) -> None:
    """先有 4 字节 .part，再次 fetch 应发 Range 并 206 追加。"""
    dest = tmp_path / "x.safetensors"
    part = dest.with_name(dest.name + ".part")
    prefix = b"HEAD"
    part.write_bytes(prefix)
    body_full = prefix + b"TAIL"
    captured_range: list[str | None] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured_range.append(req.headers.get("range"))
        return httpx.Response(206, content=body_full[4:],
                              headers={"content-range": f"bytes 4-7/{len(body_full)}"})

    fetcher = DirectURLFetcher(transport=_make_transport(handler))
    src = _src(url="https://example.com/x.safetensors")
    await fetcher.fetch(src, dest)
    assert captured_range[0] == "bytes=4-"
    assert dest.read_bytes() == body_full
    assert not part.exists()


@pytest.mark.asyncio
async def test_direct_url_200_overwrites_partial_part(tmp_path: Path) -> None:
    """服务端忽略 Range（200 + 全量）→ 截断重写 .part。"""
    dest = tmp_path / "x.safetensors"
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(b"OLD!")  # 4 字节 → Range: bytes=4-
    captured_range: list[str | None] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured_range.append(req.headers.get("range"))
        return httpx.Response(200, content=b"FRESH")

    fetcher = DirectURLFetcher(transport=_make_transport(handler))
    src = _src(url="https://example.com/x.safetensors")
    await fetcher.fetch(src, dest)
    assert captured_range[0] == "bytes=4-"  # offset>0 时仍发 Range
    assert dest.read_bytes() == b"FRESH"
    assert not part.exists()


# —— 取消 ——

@pytest.mark.asyncio
async def test_direct_url_cancel_returns_none_and_keeps_part(tmp_path: Path) -> None:
    """should_cancel() 为真时 fetch 返回 None，.part 保留供续传。"""
    body = b"X" * 8192

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    fetcher = DirectURLFetcher(chunk=128, transport=_make_transport(handler))
    dest = tmp_path / "x.safetensors"
    src = _src(url="https://example.com/x.safetensors")

    cancel_flag = {"v": False}

    def should_cancel() -> bool:
        return cancel_flag["v"]

    cancel_flag["v"] = True
    meta = await fetcher.fetch(src, dest, should_cancel=should_cancel)
    # 当前实现：取消时返回 None（而非抛 CancelledError），与 ModelScopeFetcher 对齐
    assert meta is None
    assert (dest.with_name(dest.name + ".part")).exists()
    assert not dest.exists()


# —— 字段校验 ——

@pytest.mark.asyncio
async def test_direct_url_missing_url_raises(tmp_path: Path) -> None:
    fetcher = DirectURLFetcher(transport=_make_transport(lambda r: httpx.Response(200)))
    src = ResolvedSource(SourceKind.URL)  # url 默认 ""
    from comfy_model_downloader.modelscope_client import ModelScopeError
    with pytest.raises(ModelScopeError, match="缺少 url"):
        await fetcher.fetch(src, tmp_path / "x.safetensors")


@pytest.mark.asyncio
async def test_direct_url_bad_protocol_raises(tmp_path: Path) -> None:
    fetcher = DirectURLFetcher(transport=_make_transport(lambda r: httpx.Response(200)))
    src = _src(url="ftp://example.com/x.safetensors")
    from comfy_model_downloader.modelscope_client import ModelScopeError
    with pytest.raises(ModelScopeError, match="http"):
        await fetcher.fetch(src, tmp_path / "x.safetensors")


# —— RouteFetcher 路由 ——

@pytest.mark.asyncio
async def test_route_fetcher_routes_url_to_direct(tmp_path: Path) -> None:
    body = b"URLBODY"
    direct = DirectURLFetcher(transport=_make_transport(_ok_handler(body)))

    class FakeMS:
        def __init__(self):
            self.called = False
        async def fetch(self, source, dest, *, on_progress, should_cancel):
            self.called = True
            dest.write_bytes(b"MSBODY")
            return {"path": str(dest), "size": dest.stat().st_size, "sha256": None}

    ms = FakeMS()
    router = RouteFetcher({"model": ms, "url": direct})  # type: ignore[list-item]

    # URL 走 direct
    dest1 = tmp_path / "u.safetensors"
    await router.fetch(_src(url="https://example.com/u.safetensors"), dest1,
                       on_progress=None, should_cancel=lambda: False)
    assert dest1.read_bytes() == body
    assert not ms.called

    # ModelScope 走 ms
    dest2 = tmp_path / "m.safetensors"
    await router.fetch(
        ResolvedSource(SourceKind.SEARCH, "org/repo", "m.safetensors", 123, "ab" * 32, 0.9),
        dest2,
        on_progress=None, should_cancel=lambda: False,
    )
    assert ms.called
    assert dest2.read_bytes() == b"MSBODY"


@pytest.mark.asyncio
async def test_route_fetcher_unknown_kind_raises(tmp_path: Path) -> None:
    router = RouteFetcher({})  # 路由表为空、source.kind=url 也不在内
    # kind 不在 by_kind 中、且 _default 也不在 → 抛错
    from comfy_model_downloader.modelscope_client import ModelScopeError
    with pytest.raises(ModelScopeError, match="没有可用的 fetcher"):
        await router.fetch(
            _src(url="https://example.com/x"),
            tmp_path / "x",
            on_progress=None,
            should_cancel=lambda: False,
        )


def test_build_route_fetcher_registers_both() -> None:
    r = build_route_fetcher()
    assert "model" in r._by_kind
    assert "url" in r._by_kind
    assert isinstance(r._by_kind["model"], ModelScopeFetcher)
    assert isinstance(r._by_kind["url"], DirectURLFetcher)
    assert r._default is r._by_kind["model"]


# —— hf-mirror URL 改写 ——

class _RewriteEnabled:
    pass

class _RewriteDisabled:
    pass


def test_rewrite_hf_url_https_default() -> None:
    url = "https://huggingface.co/black-forest-labs/FLUX.1-dev/resolve/main/flux1-dev.safetensors"
    out = DirectURLFetcher.rewrite_hf_url(url)
    assert out == "https://hf-mirror.com/black-forest-labs/FLUX.1-dev/resolve/main/flux1-dev.safetensors"


def test_rewrite_hf_url_preserves_path_and_query() -> None:
    url = "https://huggingface.co/owner/repo/resolve/main/file.bin?download=true"
    out = DirectURLFetcher.rewrite_hf_url(url)
    assert out == "https://hf-mirror.com/owner/repo/resolve/main/file.bin?download=true"


def test_rewrite_hf_url_disabled_returns_original() -> None:
    url = "https://huggingface.co/owner/repo/file.bin"
    out = DirectURLFetcher.rewrite_hf_url(url, enabled=False)
    assert out == url


def test_rewrite_hf_url_passthrough_for_other_hosts() -> None:
    for url in (
        "https://example.com/foo.bin",
        "https://civitai.com/models/123",
        "https://hf-mirror.com/owner/repo/file.bin",
        "https://cas-bridge.xethub.hf.co/xet-bridge-us/abc/file",
    ):
        assert DirectURLFetcher.rewrite_hf_url(url) == url


def test_rewrite_hf_url_http_and_https_both() -> None:
    out_https = DirectURLFetcher.rewrite_hf_url("https://huggingface.co/x/y")
    out_http = DirectURLFetcher.rewrite_hf_url("http://huggingface.co/x/y")
    assert out_https == "https://hf-mirror.com/x/y"
    assert out_http == "http://hf-mirror.com/x/y"


@pytest.mark.asyncio
async def test_fetch_uses_rewritten_url(tmp_path: Path, monkeypatch) -> None:
    """fetch 真的把 huggingface.co 改成 hf-mirror.com 后才发请求。"""
    monkeypatch.delenv("COMFY_FETCH_NO_HF_MIRROR", raising=False)
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, content=b"OK")

    fetcher = DirectURLFetcher(transport=_make_transport(handler))
    src = _src(url="https://huggingface.co/owner/repo/file.safetensors")
    await fetcher.fetch(src, tmp_path / "x.safetensors")
    assert len(captured) == 1
    assert str(captured[0].url).startswith("https://hf-mirror.com/")


@pytest.mark.asyncio
async def test_fetch_with_no_mirror_env_keeps_original(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("COMFY_FETCH_NO_HF_MIRROR", "1")
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, content=b"OK")

    fetcher = DirectURLFetcher(transport=_make_transport(handler))
    src = _src(url="https://huggingface.co/owner/repo/file.safetensors")
    await fetcher.fetch(src, tmp_path / "x.safetensors")
    assert len(captured) == 1
    assert str(captured[0].url).startswith("https://huggingface.co/")