"""ModelScope（魔搭社区）接入层。

本模块实现两个协议，与其余业务逻辑解耦：

* :class:`ModelScopeIndex` —— 实现 ``resolver.SourceIndex``：搜索候选仓库、列出仓库文件。
* :class:`ModelScopeFetcher` —— 实现 ``downloader.ModelFetcher``：把单个文件流式落到目标路径。

匿名即可访问全部公开模型；token 只对私有库与限流有用，因此默认不带。
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

import httpx

_LOG = logging.getLogger(__name__)

from .plan import Candidate, ResolvedSource
from .resolver import RemoteFile, normalize

DEFAULT_ENDPOINT = "https://modelscope.cn"
LEGACY_PREFIX = "/api/v1"
DOLPHIN_SEARCH = f"{LEGACY_PREFIX}/dolphin/models"
CHUNK = 1 << 20
USER_AGENT = "comfy-ui-model-downloader/0.1.12 (ModelScope client)"
_REDIRECTS = frozenset({301, 302, 303, 307, 308})


class ModelScopeError(RuntimeError):
    """ModelScope 交互失败。"""


def _endpoint() -> str:
    return (os.environ.get("MODELSCOPE_ENDPOINT") or DEFAULT_ENDPOINT).rstrip("/")


def _repo_weight(query: str, name: str, downloads: int, stars: int) -> float:
    """仓库级匹配分，落在 [0, 1]。

    查询词通常就是工作流里的文件名，仓库名是它的变体，因此以包含关系为主、
    相似度兜底；下载量与点赞数只做微调，避免热度盖过名称匹配。
    """
    q, n = normalize(query), normalize(name)
    if not q or not n:
        return 0.0
    if q == n:
        score = 1.0
    elif q in n or n in q:
        score = 0.85
    else:
        score = SequenceMatcher(None, q, n).ratio()
    if downloads >= 10_000:
        score += 0.05
    elif downloads >= 1_000:
        score += 0.03
    if stars >= 50:
        score += 0.02
    return min(1.0, score)


@dataclass(frozen=True, slots=True)
class _RepoHit:
    repo_id: str
    name: str
    score: float
    downloads: int = 0
    stars: int = 0
    chinese_name: str = ""


class ModelScopeIndex:
    """搜索候选仓库 + 读取仓库文件清单（含 size 与 sha256）。"""

    def __init__(
        self,
        token: str | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._token = token or os.environ.get("MODELSCOPE_API_TOKEN")
        self._timeout = timeout
        self._endpoint = _endpoint()
        self._transport = transport
        self._api: Any = None
        self._file_cache: dict[str, tuple[RemoteFile, ...]] = {}
        self._last_error: Exception | None = None

    @property
    def token_set(self) -> bool:
        return bool(self._token)

    def _hub_api(self) -> Any:
        if self._api is None:
            from modelscope_hub import HubApi

            self._api = HubApi()
        return self._api

    # ------------------------------------------------------------------ 搜索

    def search(self, query: str, *, category: str, limit: int = 10) -> list[Candidate]:
        """按文件名搜仓库。category 仅用于日志与未来按任务域过滤。"""
        del category
        hits = self._search_dolphin(query, limit) or self._search_openapi(query, limit)
        return [
            Candidate(repo_id=h.repo_id, file_path="", score=h.score)
            for h in hits
            if h.score > 0
        ][:limit]

    def _search_dolphin(self, query: str, limit: int) -> list[_RepoHit]:
        """dolphin 搜索是魔搭官网自己的接口，带中文名与下载量排序，且两个包都没封装。"""
        payload = {
            "PageSize": max(limit, 20),
            "PageNumber": 1,
            "Name": query,
            "Sort": "Default",
            "Target": "",
            "SingleCriterion": [],
        }
        headers = {"User-Agent": USER_AGENT}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True,
                          transport=self._transport) as client:
                resp = client.put(
                    f"{self._endpoint}{DOLPHIN_SEARCH}",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            _LOG.warning("dolphin search failed: %s", exc)
            self._last_error = exc
            return []

        data = body.get("Data") or {}
        models = ((data.get("Model") or {}).get("Models")) or []
        hits: list[_RepoHit] = []
        for item in models:
            if not isinstance(item, dict):
                continue
            name = str(item.get("Name") or "").strip()
            owner = str(item.get("Path") or "").strip().strip("/")
            if not name:
                continue
            if item.get("Visibility") in {"private", "Private"}:
                continue
            repo_id = f"{owner}/{name}" if owner else name
            score = _repo_weight(
                query,
                name if not owner else f"{owner} {name}",
                int(item.get("Downloads") or 0),
                int(item.get("Stars") or 0),
            )
            chinese = str(item.get("ChineseName") or "")
            if chinese and normalize(query) and normalize(query) in normalize(chinese):
                score = max(score, 0.9)
            hits.append(_RepoHit(repo_id, name, score, int(item.get("Downloads") or 0),
                                 int(item.get("Stars") or 0), chinese))
        return hits

    def _search_openapi(self, query: str, limit: int) -> list[_RepoHit]:
        try:
            page = self._hub_api().list_repos(
                "model", search=query, page_number=1, page_size=limit
            )
        except Exception as exc:  # noqa: BLE001 - 任何 SDK 异常都退化为"无结果"
            _LOG.warning("openapi search failed: %s", exc)
            self._last_error = exc
            return []
        items = getattr(page, "items", None) or (page or {}).get("models") or []
        out: list[_RepoHit] = []
        for repo in items:
            repo_id = getattr(repo, "repo_id", None) or (repo.get("id") if isinstance(repo, dict) else "")
            if not repo_id:
                continue
            out.append(
                _RepoHit(
                    repo_id=repo_id,
                    name=repo_id.rsplit("/", 1)[-1],
                    score=_repo_weight(
                        query,
                        repo_id,
                        int(getattr(repo, "downloads", 0) or 0),
                        int(getattr(repo, "likes", 0) or 0),
                    ),
                    downloads=int(getattr(repo, "downloads", 0) or 0),
                    stars=int(getattr(repo, "likes", 0) or 0),
                )
            )
        return out

    # -------------------------------------------------------------- 文件清单

    def list_files(self, repo_id: str) -> list[RemoteFile]:
        cached = self._file_cache.get(repo_id)
        if cached is not None:
            return list(cached)
        try:
            infos = self._hub_api().list_repo_files(repo_id, "model")
        except Exception as exc:  # noqa: BLE001 - 仓库不存在/私有/网络抖动都等价于"取不到"
            raise ModelScopeError(f"读取仓库文件列表失败 {repo_id}: {exc}") from exc
        files = tuple(
            RemoteFile(
                name=getattr(i, "name", "") or str(i.path).rsplit("/", 1)[-1],
                path=str(i.path),
                size=int(i.size) if i.size is not None else None,
                sha256=(i.sha256 or None) if isinstance(i.sha256, str) and i.sha256 else None,
            )
            for i in infos
            if not getattr(i, "is_dir", False)
        )
        self._file_cache[repo_id] = files
        return list(files)

    def find_file(self, repo_id: str, file_path: str) -> RemoteFile | None:
        """按仓库内全路径取文件，兼容只给了 basename 的情况。"""
        target = file_path.lstrip("/")
        for f in self.list_files(repo_id):
            if f.path == target or f.basename == target.rsplit("/", 1)[-1]:
                return f
        return None


class ModelScopeFetcher:
    """把 ModelScope 上的单个文件流式写到目标路径，支持断点续传。

    刻意不用 SDK 的 ``download_file``：它是同步阻塞且没有进度回调，
    20GB 的下载拿不到任何进度。这里改成两段式 httpx 请求，
    第二段（CDN）不带任何鉴权头，避免 token 随 302 泄漏到对象存储。
    """

    def __init__(
        self,
        token: str | None = None,
        timeout: float = 30.0,
        chunk: int = CHUNK,
        connect: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = token or os.environ.get("MODELSCOPE_API_TOKEN")
        self._timeout = timeout
        self._connect = connect
        self._chunk = chunk
        self._transport = transport

    def _auth_headers(self) -> dict[str, str]:
        headers = {"User-Agent": USER_AGENT}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
            headers["Cookie"] = f"m_session_id={self._token}"
        return headers

    async def fetch(
        self,
        source: ResolvedSource,
        dest: Path,
        *,
        on_progress: Any = None,
        should_cancel: Any = None,
    ) -> dict[str, Any]:
        if not source.repo_id or not source.file_path:
            raise ModelScopeError("来源缺少 repo_id 或 file_path，无法下载")
        part = dest.with_name(dest.name + ".part")
        dest.parent.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout, connect=self._connect),
            follow_redirects=False,
            transport=self._transport,
        ) as client:
            target, authed = await self._resolve_target(client, source)
            written = await self._stream(client, target, part, authed, on_progress, should_cancel)

        if written is None:
            raise asyncio.CancelledError()
        if source.size is not None and written == 0 and part.exists() and part.stat().st_size != source.size:
            part.unlink(missing_ok=True)
            raise ModelScopeError(
                f"下载异常：本地 part {part.stat().st_size}B 与期望 {source.size}B 不一致"
            )
        if written and part.exists():
            part.replace(dest)
        return {"path": str(dest), "size": dest.stat().st_size if dest.exists() else written,
                "sha256": source.sha256}

    async def _resolve_target(
        self, client: httpx.AsyncClient, source: ResolvedSource
    ) -> tuple[str, bool]:
        """第一段：请求 legacy 下载入口，取回真正的 CDN 地址。

        返回 (url, 是否可携带鉴权头)。legacy 入口对 LFS blob 回 302，
        重定向目标跨域，必须换成不带鉴权的第二次请求。
        """
        url = (
            f"{_endpoint()}{LEGACY_PREFIX}/models/{source.repo_id}/repo"
        )
        params = {
            "Revision": source.revision or "master",
            "FilePath": source.file_path.lstrip("/"),
        }
        resp = await client.get(url, params=params, headers=self._auth_headers())
        if resp.status_code in _REDIRECTS:
            location = resp.headers.get("location")
            if not location:
                raise ModelScopeError(f"下载重定向缺少 Location: {source.repo_id}")
            return location, False
        if resp.status_code >= 400:
            raise ModelScopeError(
                f"下载请求失败 HTTP {resp.status_code}: {source.repo_id}/{source.file_path}"
            )
        # 非 LFS 小文件直接在入口就返回内容体，转成 data: 让上层走同一条流式路径
        return str(resp.request.url), True

    async def _stream(
        self,
        client: httpx.AsyncClient,
        url: str,
        part: Path,
        authed: bool,
        on_progress: Any,
        should_cancel: Any,
    ) -> int | None:
        headers = self._auth_headers() if authed else {"User-Agent": USER_AGENT}
        offset = part.stat().st_size if part.exists() else 0
        if offset:
            headers["Range"] = f"bytes={offset}-"

        async with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code == 416:
                return offset
            if resp.status_code >= 400:
                _safe = urlsplit(url)
                raise ModelScopeError(
                    f"下载失败 HTTP {resp.status_code}（{_safe.netloc}{_safe.path}）"
                )
            append = resp.status_code == 206
            if not append:
                offset = 0
            total = _total_from(resp, offset)
            written = offset
            mode = "ab" if append else "wb"
            with part.open(mode) as fh:
                if on_progress:
                    on_progress(written, total)
                async for chunk in resp.aiter_bytes(self._chunk):
                    if should_cancel and should_cancel():
                        return None
                    fh.write(chunk)
                    written += len(chunk)
                    if on_progress:
                        on_progress(written, total)
        return written


def _total_from(resp: httpx.Response, offset: int) -> int:
    """从 Content-Range / Content-Length 推断总大小。"""
    crange = resp.headers.get("content-range", "")
    if "/" in crange:
        tail = crange.rsplit("/", 1)[-1].strip()
        if tail.isdigit():
            return int(tail)
    length = resp.headers.get("content-length")
    if length and length.isdigit():
        return offset + int(length)
    return 0


def build_index(token: str | None = None) -> ModelScopeIndex:
    return ModelScopeIndex(token=token)


def build_fetcher(token: str | None = None, timeout: float = 30.0) -> ModelScopeFetcher:
    return ModelScopeFetcher(token=token, timeout=timeout)


class DirectURLFetcher:
    """从任意 HTTPS 直连 URL 拉文件——覆盖 ComfyUI-Manager 走 HF/CivitAI 镜像 + HF_TOKEN
    等场景：用户在 UI 粘贴 ``https://huggingface.co/.../resolve/main/x.safetensors`` 即可。

    与 ``ModelScopeFetcher`` 的差别：单段请求、follow_redirects=True、可选 Authorization
    头（用于 HF private/gated 仓库），无两段式鉴权隔离需求。

    默认自动把 ``huggingface.co`` URL 改写到 ``hf-mirror.com``（国内镜像），绕过 HF 直连限制。
    关掉：环境变量 ``COMFY_FETCH_NO_HF_MIRROR=1``。
    """

    #: 顺序映射：先尝试列表内镜像，命中第一个替换 host 部分。
    _HF_MIRROR_HOSTS: tuple[tuple[str, str], ...] = (
        ("huggingface.co", "hf-mirror.com"),
    )

    _DEFAULT_HOSTS: frozenset[str] = frozenset({
        "huggingface.co",
        "hf-mirror.com",
        "civitai.com",
        "github.com",
        "objects.githubusercontent.com",
        "example.com",
    })

    def __init__(
        self,
        token: str | None = None,
        timeout: float = 30.0,
        chunk: int = CHUNK,
        connect: float = 30.0,
        auth_header: str = "Authorization",
        transport: httpx.AsyncBaseTransport | None = None,
        allowed_hosts: Iterable[str] | None = None,
    ) -> None:
        self._token = token or os.environ.get("DIRECT_URL_TOKEN") or os.environ.get("HF_TOKEN") or os.environ.get("CIVITAI_TOKEN")
        self._timeout = timeout
        self._connect = connect
        self._chunk = chunk
        self._auth_header = auth_header
        self._transport = transport
        self._enable_hf_mirror = os.environ.get("COMFY_FETCH_NO_HF_MIRROR") != "1"

        allowed: set[str] = set(self._DEFAULT_HOSTS)
        env_extra = os.environ.get("DIRECT_URL_ALLOWED_HOSTS", "")
        if env_extra:
            allowed.update(h.strip().lower() for h in env_extra.split(",") if h.strip())
        if allowed_hosts is not None:
            allowed.update(h.lower() for h in allowed_hosts if h)
        self._allowed_hosts: frozenset[str] = frozenset(allowed)

    @classmethod
    def rewrite_hf_url(cls, url: str, *, enabled: bool = True) -> str:
        """把 ``https://huggingface.co/...`` 改写到 ``https://hf-mirror.com/...``。
        ``enabled=False`` 时原样返回。改写只匹配 host 部分（保留 path / query）。"""
        if not enabled:
            return url
        for src, dst in cls._HF_MIRROR_HOSTS:
            for prefix in ("https://", "http://"):
                full = prefix + src
                if url.startswith(full + "/") or url == full:
                    return prefix + dst + url[len(full):]
        return url

    async def fetch(
        self,
        source: ResolvedSource,
        dest: Path,
        *,
        on_progress: Any = None,
        should_cancel: Any = None,
    ) -> dict[str, Any]:
        if not source.url:
            raise ModelScopeError("直连来源缺少 url 字段")
        url = self.rewrite_hf_url(source.url, enabled=self._enable_hf_mirror)
        if not url.startswith("https://"):
            raise ModelScopeError(f"直连 URL 必须以 https 开头: {url}")
        host = (urlsplit(url).hostname or "").lower()
        token_allowed = bool(self._token) and host in self._allowed_hosts
        part = dest.with_name(dest.name + ".part")
        dest.parent.mkdir(parents=True, exist_ok=True)

        headers: dict[str, str] = {"User-Agent": USER_AGENT}
        if token_allowed:
            headers[self._auth_header] = f"Bearer {self._token}"

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout, connect=self._connect),
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            offset = part.stat().st_size if part.exists() else 0
            if offset:
                headers["Range"] = f"bytes={offset}-"

            async with client.stream("GET", url, headers=headers) as resp:
                if resp.status_code == 416:
                    if source.size is not None and offset != source.size:
                        raise ModelScopeError(
                            f"直连断点续传失败：本地 part {offset}B 与期望 {source.size}B 不一致"
                        )
                    written = offset
                elif resp.status_code >= 400:
                    _safe = urlsplit(url)
                    raise ModelScopeError(
                        f"直连下载失败 HTTP {resp.status_code}（{_safe.netloc}{_safe.path}）"
                    )
                else:
                    append = resp.status_code == 206
                    if not append:
                        offset = 0
                    total = _total_from(resp, offset)
                    written = offset
                    mode = "ab" if append else "wb"
                    with part.open(mode) as fh:
                        if on_progress:
                            on_progress(written, total)
                        async for chunk in resp.aiter_bytes(self._chunk):
                            if should_cancel and should_cancel():
                                raise asyncio.CancelledError()
                            fh.write(chunk)
                            written += len(chunk)
                            if on_progress:
                                on_progress(written, total)

        if written is None:
            raise asyncio.CancelledError()
        if part.exists():
            part.replace(dest)
        return {
            "path": str(dest),
            "size": dest.stat().st_size if dest.exists() else written,
            "sha256": source.sha256,
        }


def build_url_fetcher(token: str | None = None, timeout: float = 30.0) -> DirectURLFetcher:
    return DirectURLFetcher(token=token, timeout=timeout)


class RouteFetcher:
    """按 ``source.kind`` 路由到 ModelScope / 直连 URL / 其他下层 fetcher。

    让 DownloadManager 仍接收一个 fetcher，但 ``fetch`` 时根据 ``source.kind``
    派发到实际下载实现。增加新源时只需注册，无需改 manager 与 server。
    """

    def __init__(self, by_kind: dict[str, ModelFetcher]) -> None:
        self._by_kind = by_kind
        self._default = by_kind.get("model")

    async def fetch(self, source, dest, *, on_progress, should_cancel):
        kind = getattr(source, "kind", None) or "model"
        impl = self._by_kind.get(kind) or self._default
        if impl is None:
            raise ModelScopeError(f"没有可用的 fetcher：kind={kind!r}")
        return await impl.fetch(source, dest, on_progress=on_progress, should_cancel=should_cancel)


def build_route_fetcher(token: str | None = None, timeout: float = 30.0) -> RouteFetcher:
    return RouteFetcher({
        "model": ModelScopeFetcher(token=token, timeout=timeout),
        "url":   DirectURLFetcher(token=token, timeout=timeout),
    })


__all__ = [
    "ModelScopeError",
    "ModelScopeIndex",
    "ModelScopeFetcher",
    "DirectURLFetcher",
    "RouteFetcher",
    "build_index",
    "build_fetcher",
    "build_url_fetcher",
    "build_route_fetcher",
]
