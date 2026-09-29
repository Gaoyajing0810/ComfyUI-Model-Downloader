"""parser / mapping 的行为测试：三种 workflow 格式、类别判定、误判防护。"""

from __future__ import annotations

import pytest

from comfy_model_downloader.mapping import guess_category, looks_like_model_file, primary_dir, sanitize_subpath
from comfy_model_downloader.parser import WorkflowParseError, load_workflow, parse_workflow


def _cats(result) -> dict[str, str]:
    return {r.filename: r.category for r in result.refs}


def test_ui_format_checkpoint() -> None:
    wf = {
        "last_node_id": 1,
        "nodes": [
            {
                "id": 1,
                "type": "CheckpointLoaderSimple",
                "widgets_values": ["Realistic_Vision_V5.1.safetensors", 420],
            }
        ],
        "links": [],
    }
    res = parse_workflow(wf)
    assert res.fmt == "ui"
    assert res.node_count == 1
    assert res.refs[0].category == "checkpoints"
    assert res.refs[0].rule.startswith("class:")


def test_api_format_all_native_loaders() -> None:
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "base.safetensors"}},
        "2": {"class_type": "LoraLoader", "inputs": {"lora_name": "style.safetensors", "strength_model": 1.0}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "vae_x.safetensors"}},
        "4": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux1-dev.safetensors", "weight_dtype": "default"}},
        "5": {"class_type": "CLIPLoader", "inputs": {"clip_name": "t5xxl.safetensors", "type": "flux"}},
        "6": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": "CLIP-ViT-H-14.safetensors"}},
        "7": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": "canny.safetensors"}},
        "8": {"class_type": "StyleModelLoader", "inputs": {"style_model_name": "style_model.safetensors"}},
    }
    cats = _cats(parse_workflow(wf))
    assert cats == {
        "base.safetensors": "checkpoints",
        "style.safetensors": "loras",
        "vae_x.safetensors": "vae",
        "flux1-dev.safetensors": "diffusion_models",
        "t5xxl.safetensors": "text_encoders",
        "CLIP-ViT-H-14.safetensors": "clip_vision",
        "canny.safetensors": "controlnet",
        "style_model.safetensors": "style_models",
    }


def test_enum_values_are_not_models() -> None:
    wf = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux1-dev.safetensors", "weight_dtype": "fp8_e4m3fn"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "a.safetensors", "clip_name2": "b.safetensors", "type": "flux"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "a beautiful girl, 8k"}},
    }
    names = {r.filename for r in parse_workflow(wf).refs}
    assert names == {"flux1-dev.safetensors", "a.safetensors", "b.safetensors"}


def test_widget_positional_enum_rejected() -> None:
    wf = {"nodes": [{"id": 1, "type": "DualCLIPLoader",
                     "widgets_values": ["clip_l.safetensors", "t5xxl_fp8.safetensors", "flux"]}]}
    assert _cats(parse_workflow(wf)) == {
        "clip_l.safetensors": "text_encoders",
        "t5xxl_fp8.safetensors": "text_encoders",
    }


def test_widgets_dict_format() -> None:
    wf = {"nodes": [{"id": 1, "type": "UnknownLoader",
                     "widgets_values": {"model_path": "vae-ft-mse.safetensors"}}]}
    assert _cats(parse_workflow(wf)) == {"vae-ft-mse.safetensors": "vae"}


def test_subgraph_is_traversed_and_counted() -> None:
    wf = {
        "version": 0.4,
        "state": {"nodes": [{"id": 1, "type": "DualCLIPLoader",
                             "widgets_values": ["clip_l.safetensors", "t5xxl.safetensors", "flux"]}]},
        "definitions": {"subgraphs": [{"id": "s1", "nodes": [
            {"id": 9, "type": "ControlNetLoader", "widgets_values": ["canny_xl.safetensors", 0, 0]}]}]},
    }
    res = parse_workflow(wf)
    assert res.subgraph_count == 1
    assert "canny_xl.safetensors" in _cats(res)


def test_custom_node_filename_fallback() -> None:
    wf = {"nodes": [{"id": 1, "type": "MyCustomIPAdapter",
                     "widgets_values": ["ip-adapter-plus_sdxl_vit-h.safetensors", 1.0, "linear"]}]}
    assert _cats(parse_workflow(wf))["ip-adapter-plus_sdxl_vit-h.safetensors"] == "ipadapter"


def test_prompt_text_never_matched() -> None:
    wf = {"nodes": [{"id": 1, "type": "CLIPTextEncode", "widgets_values": ["a beautiful girl, 8k, lora, vae"]}]}
    assert parse_workflow(wf).refs == []


def test_empty_workflow_is_not_an_error() -> None:
    assert parse_workflow({"nodes": []}).refs == []


def test_garbage_input_raises() -> None:
    with pytest.raises(WorkflowParseError):
        parse_workflow(["not", "a", "workflow"])


def test_dedup_keeps_first_occurrence() -> None:
    wf = {
        "1": {"class_type": "LoraLoader", "inputs": {"lora_name": "same.safetensors"}},
        "2": {"class_type": "LoraLoaderModelOnly", "inputs": {"lora_name": "same.safetensors"}},
    }
    assert len(parse_workflow(wf).refs) == 1


def test_load_workflow_accepts_bytes_and_path(tmp_path) -> None:
    import json

    payload = {"nodes": [{"id": 1, "type": "VAELoader", "widgets_values": ["v.safetensors"]}]}
    assert load_workflow(json.dumps(payload).encode()).refs
    p = tmp_path / "wf.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    assert load_workflow(p).refs
    assert load_workflow(payload).refs


@pytest.mark.parametrize(
    "raw",
    ["../../etc/passwd", "a/../../b.safetensors", "/abs/x.safetensors", "C:\\win\\x.safetensors"],
)
def test_sanitize_subpath_never_escapes_root(raw: str) -> None:
    clean = sanitize_subpath(raw)
    assert ".." not in clean.split("/")
    assert not clean.startswith("/")
    assert ":" not in clean


def test_looks_like_model_file_uses_category_whitelist() -> None:
    assert looks_like_model_file("a.safetensors", "checkpoints")
    assert not looks_like_model_file("a.yaml", "checkpoints")
    assert looks_like_model_file("a.yaml", "configs")
    assert looks_like_model_file("a.gguf", "vae")
    assert not looks_like_model_file("default", "diffusion_models")


def test_primary_dir_of_multi_root_categories() -> None:
    assert primary_dir("text_encoders") == "text_encoders"
    assert primary_dir("diffusion_models") == "unet"
    assert primary_dir("controlnet") == "controlnet"


def test_guess_category_priority() -> None:
    assert guess_category("UNETLoader", "unet_name", "flux1-dev.safetensors").category == "diffusion_models"
    assert guess_category("Custom", "lora_name", "x.safetensors").category == "loras"
    assert guess_category("Custom", "whatever", "vae_thing.safetensors").category == "vae"
    assert guess_category("Custom", "whatever", "mystery.bin").category is None
