# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.13] — 2026-10-01

### Added

- **workflow:** Conventional Commits + SemVer + Keep a Changelog 自动化
- **audit:** 二轮全审 + 10 项 + 5 条尾巴 + E1-E7 修复 + v0.1.12 重打包

### Changed

Gaoyajing
Initial commit

## [0.1.12] — 2026-09-30

### Added
- **CHANGELOG.md** + Conventional Commits 自动化：`scripts/bump_version.py` 现在能解析 `git log <last_tag>..HEAD` 的 conventional prefix（`feat:` / `fix:` / `feat!:` / `BREAKING CHANGE` 等），自动决定 bump 等级并同步版本号 + 写本文件
- **二级全审 E1-E7 落地**（详细见 `HANDOFF.md`）

### Changed
- **CLI 可见性**（E1）：`fetch --json` 不再被人表格污染；失败条目优先显示 error 而非 dest
- **重启打包**：0.1.11 → 0.1.12；spec `BUILD = datetime.now()` 自动生成 `CFBundleVersion`

### Fixed
- **XSS 4 处**（E2）：`parse.format`、`data-id` 两处、`model_file_count` 全部转义
- **任务 stuck "running" 根因**（E3）：`safe_join` ValueError 不再杀整批；gather `return_exceptions=True`；runner done callback 取 `t.exception()` 落 `logging.exception`；`DirectURLFetcher` 取消时 `raise CancelledError` 对齐 `ModelScopeFetcher` 契约
- **cancelTask 假象**（E4）：前端 `api.cancelTask()` non-mock 模式现在真调 `/api/task/{id}/cancel`；`startDownload` 入口 `btn.disabled` 防双击并发
- **config.py 一致性**（E5）：`pick()` env 优先（符合 docstring）；`save()` 原子写（tmp + fsync + `os.replace`）保留非本类的 key；不再吞掉 retries/timeout/booleans/token
- **错误信息**（E6）：search 失败走 `_LOG.warning + _last_error`；HTTP 错误文本用 `urlsplit` 剥 presigned URL 的 query 串；416 size 校验防截断文件被 NO_CHECKSUM 接受；`cleanup_stale_parts` 加 `active_paths` 参数保护续传中的 `.part`
- **UI 健壮性**（E7）：toast cap 3 + clearTimeout；poll 失败 5 次 cap + 指数 backoff；WS 重连 backoff；drop `.json + <50MB` 校验；history 失败保留旧 list；CSS `.drop__file`/`.toast`/`.sheet__msg` 补 bad/warn/ok tone 规则

## [0.1.11] — 2026-09-29

### Added
- 首次正式发布到 GitHub Release（release_id 399213986）
  - `comfy-ui-model-downloader.app.zip`（67MB，arm64 双击启动）
  - `comfy-ui-model-downloader-0.1.11.tar.gz`（201KB 源码包，52 个条目）
- 全量重命名：项目名 ComfyUI Model Downloader；Python 包 `comfy_model_downloader`；CLI `comfy-ui-model-downloader`；spec `comfy-model-downloader.spec`；conda 环境名刻意保留 `comfy-fetch`
- 14 端点 FastAPI（含 12 个 REST + `/ws/heartbeat` 前台心跳）；.app 双击启动 + launcher 心跳 + `_monitor_frontend` 自动退出
- 12 个 backend 模块：mapping / parser / scan / verify / plan / resolver / modelscope_client / downloader / config / server / cli / launcher
- 前端 6 视图：导入 / 下载计划 / 下载进度 / 历史 / 校验 / 目录设置弹窗
- 品牌资产：SVG logo / iconset / icns / favicon / 头图

### Changed
- 路径全面重写为新命名；旧 `comfy-fetch` 配置目录不再被探测（用户接受）
- launcher 心跳 + 心跳超时 30 分钟兜底；`COMFY_FETCH_HEADLESS=1` 跳过交互

### Fixed
- .app PyInstaller codesign 警告保留（macOS 已知 quirk；功能不受影响）

[Unreleased]: https://github.com/Gaoyajing0810/ComfyUI-Model-Downloader/compare/v0.1.12...HEAD
[0.1.12]: https://github.com/Gaoyajing0810/ComfyUI-Model-Downloader/compare/v0.1.11...v0.1.12
[0.1.11]: https://github.com/Gaoyajing0810/ComfyUI-Model-Downloader/releases/tag/v0.1.11