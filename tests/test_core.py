"""verify / scan / plan 的行为测试，含伪造损坏 safetensors。"""

from __future__ import annotations

import json
import struct

import pytest

from comfy_model_downloader.plan import ResolvedSource, SourceKind, build_plan
from comfy_model_downloader.scan import ComfyRoot, LocalIndex
from comfy_model_downloader.verify import VerifyStatus, human_bytes, probe_safetensors, sha256_file, verify_file


def _write_safetensors(path, tensors: dict[str, int], *, payload: bytes = b"") -> None:
    header = {
        "__metadata__": {"format": "pt"},
        **{
            name: {"dtype": "F16", "shape": [n], "data_offsets": [0, n * 2]}
            for name, n in tensors.items()
        },
    }
    raw = json.dumps(header).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(raw)) + raw + payload)


def test_probe_good_safetensors(tmp_path) -> None:
    p = tmp_path / "ok.safetensors"
    _write_safetensors(p, {"a": 3, "b": 5}, payload=b"\x00" * 16)
    probe = probe_safetensors(p)
    assert probe.ok and not probe.truncated
    assert probe.tensor_count == 2


def test_probe_detects_html_error_page(tmp_path) -> None:
    p = tmp_path / "bad.safetensors"
    p.write_text("<!DOCTYPE html><html><body>404 Not Found</body></html>", encoding="utf-8")
    probe = probe_safetensors(p)
    assert not probe.ok
    assert probe.reason


def test_probe_detects_json_error_response(tmp_path) -> None:
    p = tmp_path / "err.safetensors"
    p.write_text('{"Code": 400, "Message": "AccessDenied"}', encoding="utf-8")
    assert not probe_safetensors(p).ok


def test_probe_detects_truncated_tail(tmp_path) -> None:
    p = tmp_path / "trunc.safetensors"
    _write_safetensors(p, {"a": 100}, payload=b"\x00" * 8)  # 声明 200 字节，只给 8
    probe = probe_safetensors(p)
    assert probe.truncated


def test_probe_rejects_empty(tmp_path) -> None:
    p = tmp_path / "empty.safetensors"
    p.write_bytes(b"")
    assert not probe_safetensors(p).ok


def test_sha256_known_vector(tmp_path) -> None:
    p = tmp_path / "f.bin"
    p.write_bytes(b"abc")
    assert sha256_file(p) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_verify_file_ok_and_sha_mismatch(tmp_path) -> None:
    p = tmp_path / "m.safetensors"
    _write_safetensors(p, {"a": 2}, payload=b"\x00" * 4)
    good = verify_file(p, p.stat().st_size, sha256_file(p), deep=True)
    assert good.status is VerifyStatus.OK

    bad = verify_file(p, p.stat().st_size, "0" * 64, deep=True)
    assert bad.status is VerifyStatus.SHA_MISMATCH

    wrong_size = verify_file(p, p.stat().st_size + 1, None, deep=False)
    assert wrong_size.status is VerifyStatus.SIZE_MISMATCH


def test_verify_missing_file(tmp_path) -> None:
    assert verify_file(tmp_path / "nope.safetensors", None, None, deep=False).status is VerifyStatus.MISSING


def test_human_bytes() -> None:
    assert human_bytes(0) == "0 B"
    assert human_bytes(1024) == "1.00 KB"
    assert human_bytes(1536) == "1.50 KB"
    assert human_bytes(2 * 1024**3) == "2.00 GB"


def _comfy(tmp_path):
    models = tmp_path / "models"
    for sub in ("checkpoints", "loras", "unet", "diffusion_models", "text_encoders", "clip"):
        (models / sub).mkdir(parents=True)
    return models


def test_local_index_exact_and_basename(tmp_path) -> None:
    models = _comfy(tmp_path)
    _write_safetensors(models / "checkpoints" / "base.safetensors", {"a": 1})
    _write_safetensors(models / "unet" / "flux.safetensors", {"a": 1})

    idx = LocalIndex.build(ComfyRoot.resolve(tmp_path, models), health_check=False)
    assert idx.lookup("checkpoints", "base.safetensors").status == "exact"
    assert idx.lookup("diffusion_models", "flux.safetensors").status == "exact"

    (models / "diffusion_models" / "flux.safetensors").write_bytes(b"\x00" * 4)
    idx2 = LocalIndex.build(ComfyRoot.resolve(tmp_path, models), health_check=False)
    hit = idx2.lookup("diffusion_models", "unet/flux.safetensors")
    assert hit.status == "basename"
    assert hit.exists is True
    assert hit.note


def test_local_index_missing_and_corrupt(tmp_path) -> None:
    models = _comfy(tmp_path)
    p = models / "checkpoints" / "broken.safetensors"
    p.write_text("<html>404</html>", encoding="utf-8")
    idx = LocalIndex.build(ComfyRoot.resolve(tmp_path, models), health_check=True)
    assert idx.lookup("checkpoints", "broken.safetensors").status == "corrupt"
    assert idx.lookup("checkpoints", "absent.safetensors").status == "missing"


def test_local_index_ignores_partial_files(tmp_path) -> None:
    models = _comfy(tmp_path)
    (models / "checkpoints" / "x.safetensors.part").write_bytes(b"junk")
    (models / "checkpoints" / "y.safetensors").write_bytes(b"junk")
    idx = LocalIndex.build(ComfyRoot.resolve(tmp_path, models), health_check=False)
    assert idx.lookup("checkpoints", "x.safetensors").status == "missing"
    assert idx.lookup("checkpoints", "y.safetensors").status == "exact"


def test_build_plan_merges_and_counts(tmp_path) -> None:
    from comfy_model_downloader.parser import parse_workflow

    models = _comfy(tmp_path)
    _write_safetensors(models / "checkpoints" / "have.safetensors", {"a": 1})
    idx = LocalIndex.build(ComfyRoot.resolve(tmp_path, models), health_check=False)

    wf = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "have.safetensors"}},
          "2": {"class_type": "LoraLoader", "inputs": {"lora_name": "want.safetensors"}},
          "3": {"class_type": "LoraLoader", "inputs": {"lora_name": "nomatch.safetensors"}}}
    parse_result = parse_workflow(wf)

    def resolver(category: str, filename: str, ref) -> ResolvedSource:
        if filename == "want.safetensors":
            return ResolvedSource(SourceKind.SEARCH, "org/repo", "want.safetensors", 123, "ab" * 32, 0.95)
        return ResolvedSource(SourceKind.NONE)

    plan = build_plan("j1", "wf.json", parse_result, idx, resolver,
                      models_dir=str(models), comfy_root=str(models.parent))
    totals = plan.totals()
    assert totals["total"] == 3
    assert totals["present"] == 1
    assert totals["to_download"] == 1
    assert totals["unresolved"] == 1
    assert [i.ref.filename for i in plan.downloadable] == ["want.safetensors"]
    assert plan.by_id([i.item_id for i in plan.downloadable][0]).source.repo_url.endswith("org/repo")


def test_plan_order_is_deterministic(tmp_path) -> None:
    from comfy_model_downloader.parser import parse_workflow

    models = _comfy(tmp_path)
    idx = LocalIndex.build(ComfyRoot.resolve(tmp_path, models), health_check=False)
    wf = {"1": {"class_type": "LoraLoader", "inputs": {"lora_name": "zebra.safetensors"}},
          "2": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "apple.safetensors"}},
          "3": {"class_type": "LoraLoader", "inputs": {"lora_name": "alpha.safetensors"}}}
    plan = build_plan("j", "w.json", parse_workflow(wf), idx, None, models_dir=str(models))
    order = [(i.category, i.ref.filename) for i in plan.items]
    assert order == [
        ("checkpoints", "apple.safetensors"),
        ("loras", "alpha.safetensors"),
        ("loras", "zebra.safetensors"),
    ]


def test_build_plan_offline_without_resolver(tmp_path) -> None:
    from comfy_model_downloader.parser import parse_workflow

    models = _comfy(tmp_path)
    idx = LocalIndex.build(ComfyRoot.resolve(tmp_path, models), health_check=False)
    res = parse_workflow({"1": {"class_type": "LoraLoader", "inputs": {"lora_name": "a.safetensors"}}})
    plan = build_plan("j", "w.json", res, idx, None, models_dir=str(models))
    assert plan.totals()["to_download"] == 0
    assert plan.totals()["unresolved"] == 1


def test_plan_item_target_dir_uses_primary_of_multi_root(tmp_path) -> None:
    from comfy_model_downloader.parser import parse_workflow

    models = _comfy(tmp_path)
    idx = LocalIndex.build(ComfyRoot.resolve(tmp_path, models), health_check=False)
    res = parse_workflow({"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux.safetensors"}}})
    plan = build_plan("j", "w.json", res, idx, None, models_dir=str(models))
    assert plan.items[0].target_rel == "unet/flux.safetensors"


@pytest.mark.parametrize("bad", [b"", b"\x00" * 4])
def test_probe_never_raises(tmp_path, bad) -> None:
    p = tmp_path / "x.safetensors"
    p.write_bytes(bad)
    assert probe_safetensors(p) is not None
