"""全局配置：路径、并发、鉴权。

优先级：显式参数 > 环境变量 > comfy-ui-model-downloader.toml 配置文件 > 默认值。
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONCURRENCY = 3
DEFAULT_RETRIES = 3
DEFAULT_TIMEOUT = 30.0
USER_AGENT = "comfy-ui-model-downloader/0.1.13 (+https://github.com/comfyanonymous/ComfyUI)"

_CONFIG_FILENAMES = ("comfy-ui-model-downloader.toml", ".comfy-ui-model-downloader.toml")

APP_DIR_NAME = "comfy-ui-model-downloader"


def user_config_path() -> Path:
    """用户级配置路径。打包成 .app 后 cwd 不可靠，必须有稳定位置。

    macOS 用 Application Support，其余平台退回 XDG 目录。
    """
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    elif os.name == "nt":
        appdata = os.environ.get("APPDATA")
        base = (Path(appdata) if appdata else Path.home() / "AppData" / "Roaming") / APP_DIR_NAME
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / APP_DIR_NAME
    return base / "config.toml"


def find_config_file(start: Path | None = None) -> Path | None:
    """先找用户级配置，再从当前目录向上查找项目级配置。"""
    user = user_config_path()
    if user.is_file():
        return user
    cur = (start or Path.cwd()).resolve()
    for directory in (cur, *cur.parents):
        for name in _CONFIG_FILENAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def _read_toml(path: Path | None) -> dict[str, object]:
    if path is None or not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"配置文件解析失败 {path}: {exc}") from exc


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


_PERSISTED_KEYS = frozenset({
    "comfy_root", "models_dir", "concurrency", "retries", "timeout",
    "deep_verify", "health_check_existing", "allow_basename_match", "curated_path",
})


def _toml_value(v: Any) -> str:
    """把 Python 值序列化成单行 TOML 字面量字符串。"""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


@dataclass(slots=True)
class Settings:
    """运行时设置。"""

    comfy_root: Path | None = None
    models_dir: Path | None = None
    concurrency: int = DEFAULT_CONCURRENCY
    retries: int = DEFAULT_RETRIES
    timeout: float = DEFAULT_TIMEOUT
    token: str | None = None
    token_set: bool = False
    health_check_existing: bool = True
    deep_verify: bool = True
    allow_basename_match: bool = True
    curated_path: Path | None = None
    config_file: Path | None = None
    extra: dict[str, object] = field(default_factory=dict)

    @classmethod
    def load(
        cls,
        comfy_root: str | Path | None = None,
        models_dir: str | Path | None = None,
        config_file: str | Path | None = None,
        use_config: bool = True,
    ) -> Settings:
        cfg_path = Path(config_file).expanduser().resolve() if config_file else (
            find_config_file() if use_config else None
        )
        raw = _read_toml(cfg_path)

        section = raw.get("comfy-ui-model-downloader")
        if not isinstance(section, dict):
            section = raw if isinstance(raw, dict) else {}

        def pick(key: str, env: str | None = None) -> str | None:
            if env:
                env_val = os.environ.get(env)
                if env_val:
                    return env_val
            val = section.get(key)
            if isinstance(val, str) and val:
                return val
            return None

        root = comfy_root or pick("comfy_root", "COMFY_ROOT")
        models = models_dir or pick("models_dir", "COMFY_MODELS_DIR")
        token = pick("token", "MODELSCOPE_API_TOKEN")

        cur_path = curated = None
        curated_val = section.get("curated_path")
        if isinstance(curated_val, str) and curated_val:
            cur_path = Path(curated_val).expanduser()
            if not cur_path.is_absolute() and cfg_path is not None:
                cur_path = cfg_path.parent / cur_path

        return cls(
            comfy_root=Path(root).expanduser() if root else None,
            models_dir=Path(models).expanduser() if models else None,
            concurrency=_env_int("COMFY_FETCH_CONCURRENCY", int(section.get("concurrency", DEFAULT_CONCURRENCY) or DEFAULT_CONCURRENCY)),
            retries=_env_int("COMFY_FETCH_RETRIES", int(section.get("retries", DEFAULT_RETRIES) or DEFAULT_RETRIES)),
            timeout=float(section.get("timeout", DEFAULT_TIMEOUT) or DEFAULT_TIMEOUT),
            token=token,
            token_set=bool(token),
            health_check_existing=bool(section.get("health_check_existing", True)),
            deep_verify=bool(section.get("deep_verify", True)),
            allow_basename_match=bool(section.get("allow_basename_match", True)),
            curated_path=cur_path,
            config_file=cfg_path,
        )

    def models_root(self) -> Path | None:
        if self.models_dir is not None:
            return self.models_dir
        if self.comfy_root is not None:
            return self.comfy_root / "models"
        return None

    def to_dict(self) -> dict[str, object]:
        models = self.models_root()
        return {
            "comfy_root": str(self.comfy_root) if self.comfy_root else None,
            "models_dir": str(models) if models else None,
            "concurrency": self.concurrency,
            "retries": self.retries,
            "timeout": self.timeout,
            "modelscope_token_set": self.token_set,
            "deep_verify": self.deep_verify,
            "health_check_existing": self.health_check_existing,
            "config_file": str(self.config_file) if self.config_file else None,
        }

    def save(self, path: Path | None = None) -> Path:
        """原子写入用户配置：保留未在本类的 key（含 token 等敏感字段），用临时文件 + rename 保证不写坏。"""
        target = path or user_config_path()
        try:
            existing = tomllib.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
        except (OSError, tomllib.TOMLDecodeError):
            existing = {}
        merged = {k: v for k, v in existing.items() if k not in _PERSISTED_KEYS}
        if self.comfy_root is not None:
            merged["comfy_root"] = str(self.comfy_root.as_posix())
        if self.models_dir is not None:
            merged["models_dir"] = str(self.models_dir.as_posix())
        merged["concurrency"] = int(self.concurrency)
        merged["retries"] = int(self.retries)
        merged["timeout"] = float(self.timeout)
        merged["deep_verify"] = bool(self.deep_verify)
        merged["health_check_existing"] = bool(self.health_check_existing)
        merged["allow_basename_match"] = bool(self.allow_basename_match)
        if self.curated_path:
            merged["curated_path"] = str(self.curated_path)
        lines = ["# comfy-ui-model-downloader 配置，由应用自动写入，也可手动编辑。", ""]
        for k, v in merged.items():
            lines.append(f"{k} = {_toml_value(v)}")
        body = "\n".join(lines) + "\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(body)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
        self.config_file = target
        return target
