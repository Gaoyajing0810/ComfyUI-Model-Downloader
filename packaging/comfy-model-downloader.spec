# -*- mode: python ; coding: utf-8 -*-
"""ComfyUI Model Downloader 的 macOS .app 打包配置。

构建：cd 到项目根后执行
    make release             # 一键：bump patch + PyInstaller（推荐）
    或：
    /opt/anaconda3/envs/comfy-fetch/bin/python -m PyInstaller packaging/comfy-model-downloader.spec --noconfirm

产物：dist/comfy-ui-model-downloader.app（应用名固定，不带版本号）
    打包中间 PKG / COLLECT 目录名含版本号（build/pyinstaller/comfy-ui-model-downloader-0.1.X/）
    （name / version 由 scripts/bump_version.py 与 pyproject.toml 维护）
    （conda 环境名 comfy-fetch 是开发环境名，与产品标识无关，不随改名变动）

CFBundleShortVersionString = semver（pyproject.toml version）。
CFBundleVersion = 构建时间戳（YYYYMMDDHHMMSS）。
"""

import re
from datetime import datetime
from pathlib import Path

_PYPROJECT_TEXT = (Path(SPECPATH).resolve().parent / "pyproject.toml").read_text(encoding="utf-8")
NAME = re.search(r'^\s*name\s*=\s*"([^"]+)"', _PYPROJECT_TEXT, re.MULTILINE).group(1)
VERSION = re.search(r'^\s*version\s*=\s*"([^"]+)"', _PYPROJECT_TEXT, re.MULTILINE).group(1)

BUILD = datetime.now().strftime("%Y%m%d%H%M%S")

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve().parent
PKG = ROOT / "comfy_model_downloader"

# modelscope 是 modelscope_hub 的薄壳，两者都用大量惰性导入，必须整体收集，
# 否则打包后首次搜索/下载会 ImportError
datas = [
    (str(PKG / "web"), "comfy_model_downloader/web"),
    (str(PKG / "data"), "comfy_model_downloader/data"),
]
binaries = []
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "anyio._backends._asyncio",
    "cryptography.hazmat.bindings._rust",
    "python_multipart",
    "comfy_model_downloader.launcher",
    "comfy_model_downloader.server",
    "comfy_model_downloader.config",
]

for pkg_name in ("modelscope", "modelscope_hub"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg_name)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

block_cipher = None

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "PIL", "IPython", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=f"{NAME}-{VERSION}",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=f"{NAME}-{VERSION}",
)

app = BUNDLE(
    coll,
    name="comfy-ui-model-downloader.app",
    icon=str(ROOT / "assets" / "icon.icns"),
    bundle_identifier="cn.comfyuimodeldownloader.app",
    version=VERSION,
    info_plist={
        "CFBundleName": "ComfyUI Model Downloader",
        "CFBundleDisplayName": "ComfyUI Model Downloader",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": BUILD,
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.developer-tools",
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "ComfyUI Workflow",
                "CFBundleTypeRole": "Viewer",
                "LSItemContentTypes": ["public.json"],
                "CFBundleTypeExtensions": ["json"],
            }
        ],
    },
)
