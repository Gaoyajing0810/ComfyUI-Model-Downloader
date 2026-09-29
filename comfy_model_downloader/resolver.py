"""来源解析：把「类别 + 文件名」映射到魔搭上的 repo_id + file_path。

策略优先级：本地别名表 > 魔搭站内搜索 > 仓库内文件名模糊匹配。
低置信度一律返回 None（标记为需人工确认），绝不猜。
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Protocol

from .mapping import extensions_for, strip_extension
from .plan import Candidate, ResolvedSource, SourceKind

#: 低于此分数视为不可信，交由人工确认
MIN_FILE_SCORE = 0.72
#: 低于此搜索名次不采纳
MAX_REPOS_PER_QUERY = 6


@dataclass(frozen=True, slots=True)
class RemoteFile:
    """魔搭仓库中的一个文件。"""

    name: str
    path: str
    size: int | None = None
    sha256: str | None = None

    @property
    def basename(self) -> str:
        return self.path.rsplit("/", 1)[-1] if self.path else self.name


class SourceIndex(Protocol):
    """远端来源检索能力（由 modelscope_client 实现）。"""

    def search(self, query: str, *, category: str, limit: int) -> list[Candidate]:
        """按模型名搜索仓库候选。"""
        ...

    def list_files(self, repo_id: str) -> list[RemoteFile]:
        """列出仓库全部文件。"""
        ...


def normalize(text: str) -> str:
    """归一化模型名：小写、非字母数字一律折叠、去掉常见版本/质量后缀噪声。"""
    text = unicodedata.normalize("NFKC", text)
    text = strip_extension(text).lower()
    text = re.sub(r"[\s_\-]+", "", text)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", text)


_NOISE = re.compile(r"(fp8|fp16|bf16|q4|q5|q6|q8|int8|int4|safetensors|pruned|ema|preview|vae|"
                    r"f16|f8|safetensor|2k|4k|8k|hd|pth|ckpt|pt)$")


def query_variants(filename: str) -> list[str]:
    """由文件名生成若干搜索词，从最精确到最宽泛。"""
    stem = strip_extension(filename)
    out: list[str] = []
    for raw in (stem, stem.replace("_", "-"), stem.replace("_", " ")):
        v = raw.strip()
        if v and v not in out:
            out.append(v)
    compact = re.sub(r"[-_.\s]+", "", stem)
    if compact and compact not in out:
        out.append(compact)
    return out[:3]


def file_score(target: str, candidate: str) -> float:
    """目标文件名与仓库内文件名的匹配分。"""
    t_raw, c_raw = target.lower(), candidate.lower()
    t_base, c_base = t_raw.rsplit("/", 1)[-1], c_raw.rsplit("/", 1)[-1]
    if t_base == c_base:
        return 1.0
    tn, cn = normalize(target), normalize(candidate)
    if not tn or not cn:
        return 0.0
    if tn == cn:
        return 0.96
    ratio = SequenceMatcher(None, tn, cn).ratio()
    if tn.startswith(cn) or cn.startswith(tn):
        ratio = max(ratio, 0.9)
    stripped = cn
    while _NOISE.search(stripped):
        stripped = _NOISE.sub("", stripped)
    if stripped and stripped == tn:
        ratio = max(ratio, 0.88)
    return round(ratio, 4)


class CuratedTable:
    """人工维护的 模型名 -> 魔搭来源 映射表。"""

    def __init__(self, entries: dict[str, Any] | None = None) -> None:
        self._by_key: dict[str, dict[str, Any]] = {}
        for name, value in (entries or {}).items():
            self.add(name, value)

    def add(self, name: str, value: dict[str, Any]) -> None:
        if not isinstance(value, dict) or not value.get("repo_id"):
            return
        for key in (name, normalize(name)):
            if key:
                self._by_key[key] = value

    def lookup(self, filename: str) -> dict[str, Any] | None:
        return self._by_key.get(normalize(filename))

    def __len__(self) -> int:
        return len(self._by_key)

    @classmethod
    def load(cls, path: Path | None) -> CuratedTable:
        if path is None or not path.is_file():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"别名表加载失败 {path}: {exc}") from exc
        models = raw.get("models", raw) if isinstance(raw, dict) else {}
        return cls(models if isinstance(models, dict) else {})


@dataclass(slots=True)
class _Match:
    repo_id: str
    file_path: str
    size: int | None
    sha256: str | None
    score: float


class Resolver:
    """来源解析器。"""

    def __init__(
        self,
        index: SourceIndex | None,
        curated: CuratedTable | None = None,
        max_repos: int = MAX_REPOS_PER_QUERY,
    ) -> None:
        self._index = index
        self._curated = curated or CuratedTable()
        self._max_repos = max_repos

    @property
    def offline(self) -> bool:
        return self._index is None

    def __call__(self, category: str, filename: str, ref: Any = None) -> ResolvedSource | None:
        return self.resolve(category, filename)

    def resolve(self, category: str, filename: str) -> ResolvedSource | None:
        hit = self._curated.lookup(filename)
        if hit is not None:
            return ResolvedSource(
                kind=SourceKind.CURATED,
                repo_id=hit["repo_id"],
                file_path=hit.get("file_path") or filename,
                size=hit.get("size"),
                sha256=hit.get("sha256"),
                score=1.0,
                candidates=(),
            )

        if self._index is None:
            return None

        best: _Match | None = None
        runners: list[Candidate] = []
        seen_repos: list[str] = []

        for query in query_variants(filename):
            try:
                repos = self._index.search(query, category=category, limit=self._max_repos)
            except Exception:  # noqa: BLE001 - 搜索失败降级到下一档查询词
                continue
            for rank, cand in enumerate(repos):
                if cand.repo_id in seen_repos:
                    continue
                seen_repos.append(cand.repo_id)
                # 搜索端的 score 已含仓库名相关度与下载/收藏热度；排名只作同分时的次序偏好。
                # 只按排名排序会让三粉小仓库的同名文件压过官方仓库。
                repo_weight = max(cand.score, 0.0) * 0.9 + (
                    1.0 - min(rank, max(1, len(repos) - 1)) / max(1, len(repos))
                ) * 0.1
                try:
                    files = self._index.list_files(cand.repo_id)
                except Exception:  # noqa: BLE001 - 单仓库列举失败不阻塞其它候选
                    continue
                allowed = extensions_for(category)
                match = self._best_file(filename, files, allowed)
                if match is None:
                    continue
                score = round(0.65 * match[0] + 0.35 * repo_weight, 4)
                if match[0] < MIN_FILE_SCORE:
                    runners.append(Candidate(cand.repo_id, match[1], match[0], match[2]))
                    continue
                if best is None or score > best.score:
                    best = _Match(cand.repo_id, match[1], match[2], match[3], score)
            if best is not None:
                break

        if best is None:
            return ResolvedSource(SourceKind.NONE, candidates=tuple(runners[:5]))
        kind = SourceKind.SEARCH if best.score >= 0.9 else SourceKind.FILENAME
        return ResolvedSource(
            kind=kind,
            repo_id=best.repo_id,
            file_path=best.file_path,
            size=best.size,
            sha256=best.sha256,
            score=best.score,
            candidates=tuple(runners[:5]),
        )

    @staticmethod
    def _best_file(
        target: str, files: Iterable[RemoteFile], allowed: frozenset[str] | None
    ) -> tuple[float, str, int | None, str | None] | None:
        best: tuple[float, str, int | None, str | None] | None = None
        for f in files:
            ext = ("." + f.basename.rsplit(".", 1)[-1].lower()) if "." in f.basename else ""
            if allowed and ext not in allowed:
                continue
            s = file_score(target, f.path)
            if s < MIN_FILE_SCORE:
                continue
            if best is None or s > best[0]:
                best = (s, f.path, f.size, f.sha256)
        return best


def merge_candidates(sources: Sequence[ResolvedSource]) -> list[Candidate]:
    seen: set[tuple[str, str]] = set()
    out: list[Candidate] = []
    for src in sources:
        for c in src.candidates:
            key = (c.repo_id, c.file_path)
            if key in seen:
                continue
            seen.add(key)
            out.append(c)
    return out
