# ComfyUI Model Downloader · 开发期常用命令
#
# bump / build 都是开发者显式触发的动作。

PY ?= /opt/anaconda3/envs/comfy-fetch/bin/python

.PHONY: bump test build release

# 把 patch 版本号 +1（0.1.0 → 0.1.1 → 0.1.2 → ...），并把新版本号同步到
# 6 处：pyproject / __init__ / spec / 前端 / 两处 USER_AGENT。
# 详情见 scripts/bump_version.py。
bump:
	$(PY) scripts/bump_version.py

# 跑全套测试。
test:
	$(PY) -m pytest tests/ -q

# 仅打包：产物为 dist/comfy-ui-model-downloader.app（应用名固定，不带版本号）。
# 打包中间 PKG / COLLECT 目录名含版本号（build/pyinstaller/.../）。
build:
	rm -rf build/pyinstaller
	$(PY) -m PyInstaller packaging/comfy-model-downloader.spec --noconfirm --distpath dist --workpath build/pyinstaller
	@find dist -maxdepth 1 -mindepth 1 -type d ! -name 'comfy-ui-model-downloader.app' -exec rm -rf {} +
	@rm -f dist/.DS_Store

# 一键发布：bump patch + 重打包 + 产物名含新版本号。
# 等价于"修改完代码后"的最小发布流程。
release: bump build