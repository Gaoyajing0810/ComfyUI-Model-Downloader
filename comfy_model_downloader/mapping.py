"""ComfyUI 模型目录映射规则。

数据来源（已对照 ComfyUI 官方源码核实）：
  - folder_paths.py  -> folder_names_and_paths 的键与子目录顺序
  - nodes.py         -> 各加载器节点 INPUT_TYPES 里的输入名与所属类别

设计要点：
  1. 本模块不依赖 ComfyUI 本体，可在未部署 ComfyUI 的机器上独立运行。
  2. 类别 -> 子目录是多对多（如 diffusion_models -> unet + diffusion_models），
     写入时只取第一个（主目录），查重时遍历全部。
  3. 判定优先级：类别专属规则(class_type) > 输入名规则 > 文件名扩展名/关键词兜底。
     自定义节点不认识 class_type 时，靠 2 和 3 兜住。
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# 类别定义
# ---------------------------------------------------------------------------

#: 支持的模型权重扩展名，对应 folder_paths.supported_pt_extensions
PT_EXTENSIONS: frozenset[str] = frozenset(
    {".ckpt", ".pt", ".pt2", ".bin", ".pth", ".safetensors", ".pkl", ".sft"}
)

TEXT_EXTENSIONS: frozenset[str] = frozenset({".txt", ".pt", ".bin", ".safetensors"})

#: 类别 -> ComfyUI 下的子目录（相对 models/）。第一个为主目录（写入位置）。
CATEGORY_DIRS: dict[str, tuple[str, ...]] = {
    "checkpoints": ("checkpoints",),
    "loras": ("loras",),
    "vae": ("vae",),
    "text_encoders": ("text_encoders", "clip"),
    "diffusion_models": ("unet", "diffusion_models"),
    "clip_vision": ("clip_vision",),
    "style_models": ("style_models",),
    "embeddings": ("embeddings",),
    "controlnet": ("controlnet", "t2i_adapter"),
    "gligen": ("gligen",),
    "upscale_models": ("upscale_models",),
    "latent_upscale_models": ("latent_upscale_models",),
    "photomaker": ("photomaker",),
    "hypernetworks": ("hypernetworks",),
    "audio_encoders": ("audio_encoders",),
    "background_removal": ("background_removal",),
    "frame_interpolation": ("frame_interpolation",),
    "geometry_estimation": ("geometry_estimation",),
    "optical_flow": ("optical_flow",),
    "detection": ("detection",),
    "classifiers": ("classifiers",),
    "model_patches": ("model_patches",),
    "configs": ("configs",),
    "diffusers": ("diffusers",),
    # 主流自定义节点的模型目录（不在核心 folder_paths 里，但 IPAdapter/AnimateDiff 强依赖）
    "ipadapter": ("ipadapter",),
    "animatediff": ("animatediff",),
}

#: 各类别接受的扩展名（None 表示不限）
CATEGORY_EXTENSIONS: dict[str, frozenset[str] | None] = {
    "configs": frozenset({".yaml", ".yml"}),
    "embeddings": TEXT_EXTENSIONS,
    "vae": PT_EXTENSIONS | frozenset({".gguf"}),
    "text_encoders": PT_EXTENSIONS | frozenset({".gguf"}),
    "diffusion_models": PT_EXTENSIONS | frozenset({".gguf"}),
    "upscale_models": PT_EXTENSIONS,
    "clip_vision": PT_EXTENSIONS,
    "photomaker": PT_EXTENSIONS,
    "diffusers": None,  # 目录型
}
DEFAULT_EXTENSIONS: frozenset[str] = PT_EXTENSIONS


def primary_dir(category: str) -> str:
    """返回该类别的写入主目录名。"""
    dirs = CATEGORY_DIRS.get(category)
    if not dirs:
        raise KeyError(f"未知模型类别: {category}")
    return dirs[0]


def all_dirs(category: str) -> tuple[str, ...]:
    """返回该类别需要扫描查重的全部子目录名。"""
    dirs = CATEGORY_DIRS.get(category)
    if not dirs:
        raise KeyError(f"未知模型类别: {category}")
    return dirs


def extensions_for(category: str) -> frozenset[str] | None:
    return CATEGORY_EXTENSIONS.get(category, DEFAULT_EXTENSIONS)


# ---------------------------------------------------------------------------
# 规则表
# ---------------------------------------------------------------------------

#: class_type -> 类别。原生节点全覆盖；未命中则走输入名/文件名兜底。
CLASS_RULES: dict[str, str] = {
    # --- checkpoint ---
    "CheckpointLoader": "checkpoints",
    "CheckpointLoaderSimple": "checkpoints",
    "unCLIPCheckpointLoader": "checkpoints",
    "ImageCheckpointLoader": "checkpoints",
    # --- lora ---
    "LoraLoader": "loras",
    "LoraLoaderModelOnly": "loras",
    # --- vae ---
    "VAELoader": "vae",
    # --- unet / diffusion model ---
    "UNETLoader": "diffusion_models",
    # --- text encoder ---
    "CLIPLoader": "text_encoders",
    "DualCLIPLoader": "text_encoders",
    "TripleCLIPLoader": "text_encoders",
    "CLIPLoaderSDXL": "text_encoders",
    "CLIPLoaderFlux": "text_encoders",
    "CLIPVisionLoader": "clip_vision",
    "unCLIPConditioningLoader": "clip_vision",
    "unCLIPConditioningCombined": "clip_vision",
    "LuminanceConditioning": "clip_vision",
    # --- controlnet ---
    "ControlNetLoader": "controlnet",
    "ControlNetLoaderAdvanced": "controlnet",
    "DiffControlNetLoader": "controlnet",
    "T2IAdapterModelLoader": "controlnet",
    "ControlNetApplyAdvanced": "controlnet",
    # --- misc ---
    "StyleModelLoader": "style_models",
    "GLIGENLoader": "gligen",
    "LatentUpscaleModelLoader": "latent_upscale_models",
    "ImageUpscaleWithModel": "upscale_models",
    "PhotoMakerLoader": "photomaker",
    "ImageOnlyCheckpointLoader": "checkpoints",
    "ImageOnlyCheckpointSave": "checkpoints",
}

#: 输入名（精确）-> 类别
INPUT_EXACT: dict[str, str] = {
    "ckpt_name": "checkpoints",
    "config_name": "configs",
    "lora_name": "loras",
    "vae_name": "vae",
    "unet_name": "diffusion_models",
    "clip_name1": "text_encoders",
    "clip_name2": "text_encoders",
    "clip_name3": "text_encoders",
    "clip_name": "text_encoders",
    "clip_vision_name": "clip_vision",
    "style_model_name": "style_models",
    "control_net_name": "controlnet",
    "controlnet_name": "controlnet",
    "gligen_name": "gligen",
    "gligen_model_name": "gligen",
    "upscale_model_name": "upscale_models",
    "latent_upscale_model_name": "latent_upscale_models",
    "photomaker_name": "photomaker",
    "embedding_name": "embeddings",
    "audio_encoder_name": "audio_encoders",
    "model_name": "checkpoints",
}

#: 输入名正则 -> 类别，按顺序匹配，先命中先赢
INPUT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"t2i[_-]?adapter", re.I), "controlnet"),
    (re.compile(r"latent[_-]?upscale[_-]?model", re.I), "latent_upscale_models"),
    (re.compile(r"upscale[_-]?model|upscaler", re.I), "upscale_models"),
    (re.compile(r"frame[_-]?interpolat|rife|filmmaker", re.I), "frame_interpolation"),
    (re.compile(r"background[_-]?remov", re.I), "background_removal"),
    (re.compile(r"optical[_-]?flow", re.I), "optical_flow"),
    (re.compile(r"geometry[_-]?estimat", re.I), "geometry_estimation"),
    (re.compile(r"depth[_-]?estimat|depth[_-]?anything", re.I), "geometry_estimation"),
    (re.compile(r"pose[_-]?estimat|openpose|dwpose", re.I), "geometry_estimation"),
    (re.compile(r"segment(er|ation)|sam[_-]?model|rmbg|birefnet", re.I), "detection"),
    (re.compile(r"detector|yolo", re.I), "detection"),
    (re.compile(r"lora", re.I), "loras"),
    (re.compile(r"control[_-]?net|controlnet", re.I), "controlnet"),
    (re.compile(r"gligen", re.I), "gligen"),
    (re.compile(r"style[_-]?model", re.I), "style_models"),
    (re.compile(r"photomaker", re.I), "photomaker"),
    (re.compile(r"hypernetwork", re.I), "hypernetworks"),
    (re.compile(r"audio[_-]?encoder|audio[_-]?enc", re.I), "audio_encoders"),
    (re.compile(r"clip[_-]?vision|unclip|clip[_-]?v", re.I), "clip_vision"),
    (re.compile(r"text[_-]?encoder|t5|umt5|llama", re.I), "text_encoders"),
    (re.compile(r"clip", re.I), "text_encoders"),
    (re.compile(r"vae", re.I), "vae"),
    (re.compile(r"unet|diffusion[_-]?model", re.I), "diffusion_models"),
    (re.compile(r"ckpt|checkpoint|diffusion", re.I), "checkpoints"),
    (re.compile(r"embedding|prompt", re.I), "embeddings"),
)

#: 文件名关键词 -> 类别（class_type 与输入名都判不出时的最后兜底）
FILENAME_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(^|[/\-_.])lora", re.I), "loras"),
    (re.compile(r"controlnet|control_net|t2i[_-]?adapter|openpose|dwpose|canny|scribble|depth|lineart|pose|seg|sam|bbox", re.I), "controlnet"),
    (re.compile(r"clip[_-]?vision|open[_-]?clip[_-]?vit|clip[_-]?v", re.I), "clip_vision"),
    (re.compile(r"umt5|(^|[/\-_.])t5|clip[_-]?l|clip[_-]?g|text[_-]?encoder|qwen.*vl|llama", re.I), "text_encoders"),
    (re.compile(r"(^|[/\-_.])vae|ae[._-]", re.I), "vae"),
    (re.compile(r"flux|sdxl_base|sd3|hunyuan|wan|lumina|pixart|cogvideo|mochi|ltx|kandinsky", re.I), "diffusion_models"),
    (re.compile(r"gligen", re.I), "gligen"),
    (re.compile(r"style[_-]?model", re.I), "style_models"),
    (re.compile(r"upscale|esrgan|realesrgan|hat|swinir|ultramix", re.I), "upscale_models"),
    (re.compile(r"photomaker", re.I), "photomaker"),
    (re.compile(r"embedding", re.I), "embeddings"),
    (re.compile(r"ip[_-]?adapter", re.I), "ipadapter"),
    (re.compile(r"animatediff|motion[_-]?module", re.I), "animatediff"),
)

#: 原生节点的 widgets_values 位置 -> 输入名。用于 UI 格式（位置型）解析。
#: 只列原生与高频自定义节点；未列出的节点由文件名规则兜底。
WIDGET_ORDER: dict[str, tuple[str, ...]] = {
    "CheckpointLoaderSimple": ("ckpt_name",),
    "CheckpointLoader": ("config_name", "ckpt_name"),
    "unCLIPCheckpointLoader": ("ckpt_name",),
    "LoraLoader": ("model", "clip", "lora_name", "strength_model", "strength_clip"),
    "LoraLoaderModelOnly": ("model", "lora_name", "strength_model"),
    "VAELoader": ("vae_name",),
    "UNETLoader": ("unet_name", "weight_dtype"),
    "ControlNetLoader": ("control_net_name",),
    "ControlNetLoaderAdvanced": ("control_net_name", "strength", "start_percent", "end_percent"),
    "T2IAdapterModelLoader": ("t2i_adapter_name",),
    "StyleModelLoader": ("style_model_name",),
    "CLIPVisionLoader": ("clip_name",),
    "CLIPLoader": ("clip_name", "type", "device"),
    "DualCLIPLoader": ("clip_name1", "clip_name2", "type", "device"),
    "CLIPLoaderSDXL": ("clip_name1", "clip_name2", "provider", "device"),
    "GLIGENLoader": ("gligen_name",),
    "LatentUpscaleModelLoader": ("latent_upscale_model_name",),
    "ImageUpscaleWithModel": ("upscale_model_name",),
    "PhotoMakerLoader": ("photomaker_name",),
    "unCLIPConditioningLoader": ("clip_name", "init_image", "noise_augment_config"),
    "LoraLoaderModelTagLoader": ("lora_name",),
}


@dataclass(frozen=True, slots=True)
class CategoryGuess:
    """一次判定结果。"""

    category: str | None
    rule: str
    confidence: float

    @property
    def resolved(self) -> bool:
        return self.category is not None


def guess_category(
    class_type: str | None,
    input_name: str | None = None,
    filename: str | None = None,
) -> CategoryGuess:
    """判定一个模型引用应属于哪个 ComfyUI 模型子目录。

    优先级: class_type 专属规则 > 输入名(精确/正则) > 文件名关键词。
    """
    if class_type:
        cat = CLASS_RULES.get(class_type)
        if cat:
            return CategoryGuess(cat, f"class:{class_type}", 1.0)

    if input_name:
        cat = INPUT_EXACT.get(input_name)
        if cat:
            return CategoryGuess(cat, f"input-exact:{input_name}", 0.95)
        for pattern, cat in INPUT_PATTERNS:
            if pattern.search(input_name):
                return CategoryGuess(cat, f"input-re:{pattern.pattern}", 0.8)

    if filename:
        stem = strip_extension(posixpath.basename(filename))
        for pattern, cat in FILENAME_PATTERNS:
            if pattern.search(stem):
                return CategoryGuess(cat, f"filename-re:{pattern.pattern}", 0.55)

    return CategoryGuess(None, "none", 0.0)


def strip_extension(name: str) -> str:
    """去掉 safetensors / ckpt 之类的模型扩展名。"""
    for ext in (".safetensors", ".ckpt", ".pt2", ".pth", ".pkl", ".sft", ".bin", ".pt", ".gguf"):
        if name.lower().endswith(ext):
            return name[: -len(ext)]
    return name


def looks_like_model_file(value: str, category: str | None = None) -> bool:
    """判断一个字符串是否像模型文件名（而非提示词/数字等）。"""
    if not isinstance(value, str) or not value.strip():
        return False
    if value.startswith(("data:", "http://", "https://")):
        return False
    allowed = extensions_for(category) if category else None
    ext = posixpath.splitext(value)[1].lower()
    if not ext:
        return False
    if allowed is None:
        return ext in PT_EXTENSIONS
    return ext in allowed


def sanitize_subpath(filename: str) -> str:
    """清洗模型引用中的相对子路径，剔除路径穿越与非法字符。

    ComfyUI 的模型文件名允许形如 ``subdir/foo.safetensors``。
    含盘符的输入（``C:\\...``）必须剔除首段，否则在 Windows 上会逃逸出模型根目录。
    """
    name = filename.strip().replace("\\", "/")
    parts = [p for p in name.split("/") if p not in ("", ".", "..")]
    if parts and ":" in parts[0]:
        parts = parts[1:]
    if not parts:
        raise ValueError(f"非法模型文件名: {filename!r}")
    return "/".join(parts)


def safe_join(models_root: Path, filename: str) -> Path:
    """在 models_root 下构造安全子路径，拒绝对 symlink 链的越界写入。

    先用 :func:`sanitize_subpath` 把 filename 清洗成相对子路径，
    再解析为绝对路径并断言结果仍在 models_root 解析后的边界内——
    即便用户在 models_root 下放了恶意 symlink，写入也不会落到外部目录。
    """
    clean = sanitize_subpath(filename)
    resolved_root = models_root.resolve()
    target = (resolved_root / clean).resolve()
    if not target.is_relative_to(resolved_root):
        raise ValueError(f"路径逃逸 models_root: {filename!r} -> {target}")
    return target
