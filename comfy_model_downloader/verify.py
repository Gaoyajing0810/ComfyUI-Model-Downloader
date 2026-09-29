"""下载产物完整性校验。

国内网络环境下载大模型最常见的三种失败，都不会抛异常、只会静默产出坏文件：
  1. 反代/风控返回 HTML 错误页，被当作 .safetensors 存下来
  2. 连接中断导致文件截断（大小远小于预期，或尾部缺失）
  3. sha256 不符（代理注入、缓存污染）

因此校验分三层：文件头合法性 -> 大小 -> sha256。
"""

from __future__ import annotations

import hashlib
import json
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

_SAFETENSORS_MAGIC_LEN = 8
_MAX_HEADER_BYTES = 100 * 1024 * 1024   # safetensors 头部上限 100MB，合法值通常 <10MB
_CHUNK = 1024 * 1024


class VerifyStatus(str, Enum):
    OK = "ok"
    MISSING = "missing"
    EMPTY = "empty"
    NOT_A_MODEL = "not_a_model"      # HTML 错误页 / JSON 报错 / 文本
    TRUNCATED = "truncated"
    SIZE_MISMATCH = "size_mismatch"
    SHA_MISMATCH = "sha_mismatch"
    NO_CHECKSUM = "no_checksum"       # 源未提供 sha256，只做了头部+大小校验
    IO_ERROR = "io_error"


#: 状态是否为"不可用"（需要重新下载）
BAD_STATUSES = frozenset(
    {
        VerifyStatus.MISSING,
        VerifyStatus.EMPTY,
        VerifyStatus.NOT_A_MODEL,
        VerifyStatus.TRUNCATED,
        VerifyStatus.SIZE_MISMATCH,
        VerifyStatus.SHA_MISMATCH,
    }
)


@dataclass(frozen=True, slots=True)
class SafetensorsProbe:
    """safetensors 文件头探测结果。"""

    ok: bool
    reason: str = ""
    header_bytes: int = 0
    tensor_count: int = 0
    data_bytes: int = 0
    declared_data_end: int | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def truncated(self) -> bool:
        return "截断" in self.reason or "truncat" in self.reason.lower()


@dataclass(frozen=True, slots=True)
class VerifyResult:
    status: VerifyStatus
    path: Path
    size: int = 0
    expected_size: int | None = None
    expected_sha256: str | None = None
    actual_sha256: str | None = None
    detail: str = ""
    probe: SafetensorsProbe | None = None

    @property
    def ok(self) -> bool:
        return self.status in (VerifyStatus.OK, VerifyStatus.NO_CHECKSUM)

    @property
    def needs_download(self) -> bool:
        return self.status in BAD_STATUSES

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "ok": self.ok,
            "path": str(self.path),
            "size": self.size,
            "expected_size": self.expected_size,
            "expected_sha256": self.expected_sha256,
            "actual_sha256": self.actual_sha256,
            "detail": self.detail,
            "tensors": self.probe.tensor_count if self.probe else None,
        }


# ---------------------------------------------------------------------------
# safetensors 文件头
# ---------------------------------------------------------------------------


def probe_safetensors(path: Path | str) -> SafetensorsProbe:
    """读取并校验 safetensors 文件头（只读文件前若干字节，不做全量哈希）。"""
    p = Path(path)
    try:
        size = p.stat().st_size
    except OSError as exc:
        return SafetensorsProbe(False, f"无法读取文件: {exc}")

    if size == 0:
        return SafetensorsProbe(False, "文件为空（0 字节）")

    try:
        with p.open("rb") as fh:
            head = fh.read(min(size, _CHUNK))
    except OSError as exc:
        return SafetensorsProbe(False, f"读取失败: {exc}")

    # 1) 明显不是模型的二进制内容
    sniff = head.lstrip()[:512]
    lowered = sniff.lower()
    if lowered.startswith((b"<!doctype", b"<html", b"<?xml")):
        return SafetensorsProbe(False, "内容是 HTML 页面（多半是下载源返回了错误页/登录页）")
    if lowered.startswith(b"{") and b'"error"' in lowered[:512]:
        return SafetensorsProbe(False, "内容是 JSON 错误响应，非模型权重")
    if sniff.startswith(b"\xef\xbb\xbf"):
        return SafetensorsProbe(False, "内容是 BOM 开头的文本文件，非模型权重")

    if size < _SAFETENSORS_MAGIC_LEN:
        return SafetensorsProbe(False, f"文件仅 {size} 字节，连 safetensors 头都不完整")

    (header_len,) = struct.unpack("<Q", head[:_SAFETENSORS_MAGIC_LEN])
    if header_len == 0:
        return SafetensorsProbe(False, "safetensors 头长度为 0，文件不是合法 safetensors")
    if header_len > _MAX_HEADER_BYTES:
        return SafetensorsProbe(False, f"safetensors 头长度异常（{header_len} 字节），疑似损坏或格式不符")
    if size < _SAFETENSORS_MAGIC_LEN + header_len:
        return SafetensorsProbe(
            False, f"文件被截断：头部声明 {header_len} 字节，实际只有 {max(size - _SAFETENSORS_MAGIC_LEN, 0)} 字节"
        )

    try:
        raw = p.read_bytes()[_SAFETENSORS_MAGIC_LEN : _SAFETENSORS_MAGIC_LEN + header_len] \
            if size <= _MAX_HEADER_BYTES * 2 else _read_range(p, _SAFETENSORS_MAGIC_LEN, header_len)
    except OSError as exc:
        return SafetensorsProbe(False, f"读取头部失败: {exc}")

    try:
        header = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return SafetensorsProbe(False, f"safetensors 头不是合法 JSON: {exc}", header_bytes=header_len)
    if not isinstance(header, dict):
        return SafetensorsProbe(False, "safetensors 头不是 JSON 对象", header_bytes=header_len)

    meta = header.get("__metadata__") or {}
    tensors = {k: v for k, v in header.items() if k != "__metadata__"}
    if not tensors:
        return SafetensorsProbe(False, "safetensors 头内没有任何张量", header_bytes=header_len)

    max_end = 0
    for name, spec in tensors.items():
        if not isinstance(spec, dict):
            return SafetensorsProbe(False, f"张量 {name} 的描述不是对象", header_bytes=header_len)
        offsets = spec.get("data_offsets")
        if (
            not isinstance(offsets, list)
            or len(offsets) != 2
            or not all(isinstance(v, int) for v in offsets)
        ):
            return SafetensorsProbe(False, f"张量 {name} 缺少合法 data_offsets", header_bytes=header_len)
        if offsets[0] > offsets[1]:
            return SafetensorsProbe(False, f"张量 {name} 的 data_offsets 逆序", header_bytes=header_len)
        max_end = max(max_end, offsets[1])

    data_bytes = size - _SAFETENSORS_MAGIC_LEN - header_len
    if data_bytes < max_end:
        return SafetensorsProbe(
            False,
            f"文件被截断：张量数据声明 {max_end} 字节，实际只有 {data_bytes} 字节",
            header_bytes=header_len,
            tensor_count=len(tensors),
            declared_data_end=max_end,
        )

    return SafetensorsProbe(
        ok=True,
        reason="ok",
        header_bytes=header_len,
        tensor_count=len(tensors),
        data_bytes=data_bytes,
        declared_data_end=max_end,
        metadata={str(k): str(v) for k, v in meta.items()} if isinstance(meta, dict) else {},
    )


def _read_range(path: Path, offset: int, length: int) -> bytes:
    with path.open("rb") as fh:
        fh.seek(offset)
        return fh.read(length)


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------


def sha256_file(
    path: Path | str,
    progress: Callable[[int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> str:
    """分块计算 sha256（1MB/块，可取消、可回调进度）。"""
    h = hashlib.sha256()
    done = 0
    with Path(path).open("rb") as fh:
        while True:
            if should_cancel is not None and should_cancel():
                raise InterruptedError("校验被取消")
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            h.update(chunk)
            done += len(chunk)
            if progress is not None:
                progress(done)
    return h.hexdigest()


def verify_file(
    path: Path | str,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
    deep: bool = True,
    progress: Callable[[int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> VerifyResult:
    """校验单个已下载文件。

    deep=True 时做全量 sha256；deep=False 只做文件头 + 大小校验（快很多）。
    """
    p = Path(path)
    try:
        size = p.stat().st_size
    except FileNotFoundError:
        return VerifyResult(VerifyStatus.MISSING, p, detail="文件不存在")
    except OSError as exc:
        return VerifyResult(VerifyStatus.IO_ERROR, p, detail=str(exc))

    if size == 0:
        return VerifyResult(VerifyStatus.EMPTY, p, 0, expected_size, expected_sha256, detail="0 字节")

    is_safetensors = p.name.lower().endswith(".safetensors")
    probe: SafetensorsProbe | None = None
    if is_safetensors:
        probe = probe_safetensors(p)
        if not probe.ok:
            status = VerifyStatus.TRUNCATED if probe.truncated else VerifyStatus.NOT_A_MODEL
            return VerifyResult(status, p, size, expected_size, expected_sha256,
                                detail=probe.reason, probe=probe)

    if expected_size is not None and size != expected_size:
        return VerifyResult(
            VerifyStatus.SIZE_MISMATCH, p, size, expected_size, expected_sha256,
            detail=f"大小不符：本地 {size} 字节，远端 {expected_size} 字节", probe=probe,
        )

    if expected_sha256 and deep:
        try:
            actual = sha256_file(p, progress=progress, should_cancel=should_cancel)
        except InterruptedError:
            return VerifyResult(VerifyStatus.IO_ERROR, p, size, expected_size, expected_sha256,
                                detail="校验被取消", probe=probe)
        except OSError as exc:
            return VerifyResult(VerifyStatus.IO_ERROR, p, size, expected_size, expected_sha256,
                                detail=f"读取失败: {exc}", probe=probe)
        if actual.lower() != expected_sha256.lower():
            return VerifyResult(VerifyStatus.SHA_MISMATCH, p, size, expected_size, expected_sha256,
                                actual, detail="sha256 不匹配，文件已损坏", probe=probe)
        return VerifyResult(VerifyStatus.OK, p, size, expected_size, expected_sha256,
                            actual, detail="sha256 校验通过", probe=probe)

    return VerifyResult(VerifyStatus.NO_CHECKSUM, p, size, expected_size, expected_sha256,
                        detail="远端未提供 sha256，已通过文件头与大小校验" if is_safetensors
                        else "远端未提供 sha256，已通过大小校验",
                        probe=probe)


def human_bytes(n: float | int | None) -> str:
    """把字节数格式化成人类可读形式。"""
    if n is None:
        return "-"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} TB"
