#!/usr/bin/env python3
"""Bump the semver patch version across every version-bearing file.

Reads ``pyproject.toml`` as the single source of truth, increments the patch
component by 1, then mirrors the new ``X.Y.Z`` into every place that needs to
keep step:

  * ``pyproject.toml`` (PEP 621 declaration; consumed by ``importlib.metadata``
    and ``click.version_option``)
  * ``comfy_model_downloader/__init__.py`` (fallback when
    ``importlib.metadata`` is unavailable, e.g. source-tree run without install)
  * ``packaging/comfy-model-downloader.spec`` (``CFBundleShortVersionString``)
  * ``comfy_model_downloader/web/app.js`` (front-end ``MOCK_CONFIG.version``)
  * ``comfy_model_downloader/modelscope_client.py`` (HTTP ``User-Agent``)
  * ``comfy_model_downloader/config.py`` (HTTP ``User-Agent``)

Usage::

    python scripts/bump_version.py
    make bump

Each invocation prints the old → new version and the relative paths it touched,
so the change is reviewable in a single ``diff`` afterwards.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Files that hold a single, well-known version literal.
PYPROJECT = ROOT / "pyproject.toml"
INIT = ROOT / "comfy_model_downloader" / "__init__.py"
SPEC = ROOT / "packaging" / "comfy-model-downloader.spec"
WEB_JS = ROOT / "comfy_model_downloader" / "web" / "app.js"

# Files that may carry several copies of the version inside the same file
# (the User-Agent string is referenced once as a constant and used elsewhere).
USER_AGENT_FILES = (
    ROOT / "comfy_model_downloader" / "modelscope_client.py",
    ROOT / "comfy_model_downloader" / "config.py",
)

# pyproject.toml:    version = "X.Y.Z"
PYPROJECT_RE = re.compile(
    r'^(?P<indent>\s*)version\s*=\s*"(?P<v>\d+\.\d+\.\d+)"\s*$',
    re.MULTILINE,
)

# comfy_model_downloader/__init__.py:    __version__ = "X.Y.Z"
# (kept as a fallback alongside importlib.metadata; see __init__.py docstring)
INIT_RE = re.compile(
    r'^(?P<indent>[ \t]*)(?P<prefix>__version__\s*=\s*)"[^"]+"\s*$',
    re.MULTILINE,
)

# packaging/comfy-model-downloader.spec:    VERSION = "X.Y.Z"
SPEC_RE = re.compile(
    r'^(?P<indent>[ \t]*)(?P<prefix>VERSION\s*=\s*)"[^"]+"\s*$',
    re.MULTILINE,
)

# web/app.js:    version: 'X.Y.Z',   (inside MOCK_CONFIG)
WEB_RE = re.compile(
    r"(?P<indent>^[ \t]*)(?P<prefix>version:\s*')(?P<v>[^']+)(')",
    re.MULTILINE,
)

# User-Agent:      <product>/<X.Y.Z> ...
USER_AGENT_RE = re.compile(
    r"(?P<product>comfy-ui-model-downloader/)(?P<v>\d+\.\d+(?:\.\d+)?)"
)


def read_current_version() -> tuple[int, int, int]:
    text = PYPROJECT.read_text(encoding="utf-8")
    m = PYPROJECT_RE.search(text)
    if not m:
        raise RuntimeError(
            f"Could not parse version from {PYPROJECT}. "
            "Expected a line matching: version = \"X.Y.Z\""
        )
    major, minor, patch = m.group("v").split(".")
    return int(major), int(minor), int(patch)


def replace_once(path: Path, pattern: re.Pattern[str], repl, label: str, *, optional: bool = False) -> None:
    text = path.read_text(encoding="utf-8")
    new_text, count = pattern.subn(repl, text, count=1)
    if count == 0:
        if optional:
            print(f"  (skip) {label}: pattern not found (already dynamic?)")
            return
        raise RuntimeError(
            f"Expected exactly 1 match for {label} in {path}, got 0. "
            f"Pattern: {pattern.pattern!r}"
        )
    if count != 1:
        raise RuntimeError(
            f"Expected exactly 1 match for {label} in {path}, got {count}. "
            f"Pattern: {pattern.pattern!r}"
        )
    path.write_text(new_text, encoding="utf-8")


def replace_user_agent(path: Path, new_version: str) -> int:
    """Replace every occurrence of the User-Agent version literal."""
    text = path.read_text(encoding="utf-8")
    new_text, count = USER_AGENT_RE.subn(
        lambda m: f"{m.group('product')}{new_version}", text
    )
    if count == 0:
        raise RuntimeError(
            f"No User-Agent match in {path}; "
            f"expected at least one '{USER_AGENT_RE.pattern!r}'"
        )
    path.write_text(new_text, encoding="utf-8")
    return count


def main() -> int:
    major, minor, patch = read_current_version()
    old_version = f"{major}.{minor}.{patch}"
    new_version = f"{major}.{minor}.{patch + 1}"

    # Single-occurrence version literals.
    edits = [
        (PYPROJECT, PYPROJECT_RE, rf'\g<indent>version = "{new_version}"',
         "pyproject.toml version"),
        (INIT, INIT_RE, rf'\g<indent>\g<prefix>"{new_version}"',
         "__init__.py __version__ fallback"),
        (SPEC, SPEC_RE, rf'\g<indent>\g<prefix>"{new_version}"',
         "spec VERSION (CFBundleShortVersionString; skip if already dynamic)"),
        (WEB_JS, WEB_RE, rf"\g<indent>\g<prefix>{new_version}\g<4>",
         "web/app.js MOCK_CONFIG.version"),
    ]
    for path, pattern, repl, label in edits:
        # spec 是 optional：现在 spec 自己从 pyproject 动态读，VERSION 已是变量，
        # 找不到字面量时跳过而非报错。
        optional = (path == SPEC)
        replace_once(path, pattern, repl, label, optional=optional)

    # User-Agent: may appear multiple times per file.
    for path in USER_AGENT_FILES:
        replace_user_agent(path, new_version)

    print(f"Bumped version: {old_version} → {new_version}")
    print("Updated files:")
    for p in (PYPROJECT, INIT, SPEC, WEB_JS, *USER_AGENT_FILES):
        print(f"  - {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())