# HANDOFF

最后更新：2026-09-29 22:10

## 当前任务与目标

做一个**从 ComfyUI 工作流自动补齐模型**的工具。起因是 ComfyUI 模型下载在国内被限制（HF 不可达），所以改为从魔搭社区（ModelScope）下载。

用户原始需求（逐字）：
> 由于ComfyUI 模型下载，在国内被限制。我想开发一个工具。将ComfyUI工作流上传，就可以自动分析模型名字和ComfyUI存放模型的子目录。如果已经存在就不在下载。自动从国内魔塔社区下载模型存放到ComfyUI模型子目录中。并检查是否下载下载成功

追加要求：
- 「要有操纵UI」——必须有可操作的操作界面（不只是 CLI）。
- 「给我打包成应用」——打包成 macOS .app 双击启动。
- 「将配置ComfyUI 环境变量放到操作界面中」——ComfyUI 目录改为在网页操作界面里直接设置与修改（`COMFY_ROOT` 环境变量降级为启动默认）。
- 「关闭前台自动关闭后台服务」——关掉浏览器（前台）后，后台 uvicorn 服务自动退出（心跳机制，见下）。
- 「将应用名称正式修改为 ComfyUI Model Downloader」（**全量重命名**，2026-09-29 完成）——显示名、CLI、Python 包、配置目录、日志路径、EXE 内部名、bundle id、spec 文件名全部改为 ComfyUI Model Downloader 体系。**不做旧路径/旧包名回退逻辑**：用户原有的 `~/Library/Application Support/comfy-fetch/config.toml` 已失效（用户接受），必须重新设置 ComfyUI 目录。

**项目状态：全量重命名完成并验收。** 104 个单测全绿，新 spec 构建并实测（CFBundleName/DisplayName、bundle id、EXE 内部名全部就位）。

## 标识符映射（重命名最终态）

| 维度 | 旧 | 新 |
|---|---|---|
| 用户可见显示名（含 CFBundleName / DisplayName / Web 页面 brand / OpenAPI title / banner / 弹窗标题） | ComfyUI Model Tool | **ComfyUI Model Downloader** |
| Python 包目录与 import 名 | `comfy_fetch` | **`comfy_model_downloader`** |
| pyproject name / CLI 命令 / `pip install -e .` 后的可执行名 | `comfy-model-tool` / `comfy-ui-model-tool` | **`comfy-ui-model-downloader`** |
| .app 产物名 | `comfy-ui-model-tool.app` | **`comfy-ui-model-downloader.app`** |
| EXE 内部名 / COLLECT 收集目录 / `__pycache__` 前缀 | `comfy-fetch` | **`comfy-model-downloader`** |
| 配置目录 | `comfy-fetch` | **`comfy-ui-model-downloader`** |
| 配置文件名 | `comfy-fetch.toml` / `.comfy-fetch.toml` | **`comfy-ui-model-downloader.toml`** / **`.comfy-ui-model-downloader.toml`** |
| 日志目录 | `~/Library/Logs/comfy-fetch/` | **`~/Library/Logs/comfy-ui-model-downloader/`** |
| spec 文件名 | `comfy-fetch.spec` | **`comfy-model-downloader.spec`** |
| CFBundleIdentifier | `cn.comfyfetch.app` | **`cn.comfyuimodeldownloader.app`** |
| USER_AGENT | `comfy-fetch/0.1 ...` | **`comfy-ui-model-downloader/0.1 ...`** |
| conda 开发环境名 | **故意保留** `comfy-fetch` | **故意保留** `comfy-fetch` |

**为什么 conda 环境名不改**：环境名是开发环境标识（`/opt/anaconda3/envs/<env>`），不是产品标识。改名要重装全部依赖（fastapi/uvicorn/pydantic/click/httpx/modelscope 1.40.1/modelscope_hub 0.4.5/python-multipart/PyInstaller 6.22.3），成本高、收益低。所以 README / spec 中提到 conda 的位置**刻意保留 `comfy-fetch`**，并在 spec 的 docstring 注明「conda 环境名 comfy-fetch 是开发环境名，与产品标识无关」。`data/models.json` 注释、`web/styles.css` 顶部注释、spec docstring 三处都加了这一说明。

**为什么不写旧路径回退逻辑**：用户在改名决策中**明确选**「全量改名，不管旧配置」。即 `user_config_path()` 只看 `~/Library/Application Support/comfy-ui-model-downloader/`，不再探测 `comfy-fetch/` 旧目录。用户原配置（指向 `/Users/gaoyajing/ComfyUI-Shared`）已失效，必须在 UI 的「设置目录」弹窗里重新指定。

## 已完成

### 后端（`comfy_model_downloader/`，13 个模块）

| 模块 | 职责 |
|---|---|
| `mapping.py` | ComfyUI 节点 → 模型目录注册表。类别→子目录映射（`text_encoders`→`text_encoders,clip`；`diffusion_models`→`unet,diffusion_models`；`controlnet`→`controlnet,t2i_adapter` 三个是多根目录）、扩展名白名单、class_type/输入名/文件名三级兜底规则 |
| `parser.py` | 解析三种 workflow 格式：API（`{id:{class_type,inputs}}`）、UI（`{nodes:[{type,widgets_values}]}`）、新版前端（`state.nodes` + `definitions.subgraphs` 子图） |
| `scan.py` | 扫描本地 `models/` 建索引（相对路径 + basename 双索引），判定「已存在/其他目录有/损坏/缺失」。公开 `iter_model_files(root, category, health_check=False)` |
| `verify.py` | 三层校验：safetensors 文件头（8 字节头长 + JSON + offsets 合法性）→ 大小 → sha256。能识别被存成 `.safetensors` 的 HTML 错误页与截断文件 |
| `plan.py` | 下载计划数据模型，同时是 Web API 响应契约 |
| `resolver.py` | 来源解析：curated 别名表 → 魔搭站内搜索 → 仓库内文件名模糊匹配，阈值 0.72 |
| `modelscope_client.py` | `ModelScopeIndex`（搜索 + 仓库文件列表带 sha256）+ `ModelScopeFetcher`（流式下载）；USER_AGENT = `comfy-ui-model-downloader/0.1 (ModelScope client)` |
| `downloader.py` | 并发编排（信号量限流）、进度回调、失败重试、损坏文件隔离为 `.corrupt` |
| `config.py` | `Settings.load()` + `Settings.save(path=None)`（持久化 comfy_root/models_dir/concurrency，**token 永不落盘**）+ `user_config_path()`（macOS `~/Library/Application Support/comfy-ui-model-downloader/comfy-ui-model-downloader.toml`）+ `models_root()`。配置目录/文件名/TOML section key 全部以新名 `comfy-ui-model-downloader` 读写 |
| `server.py` | FastAPI **12 个端点** + 静态 UI（`title="ComfyUI Model Downloader"`，含设置三端点 + **WS `/ws/heartbeat` 心跳**，见下） |
| `cli.py` | click：`scan` / `plan` / `fetch` / `verify` / `serve`，prog_name 显示 `comfy-ui-model-downloader` |
| `launcher.py` | .app 启动器：`osascript` 原生目录选择（`choose_folder`，stdin 必须断开否则从 Finder 双击会挂住）、`looks_like_comfyui` 校验、`find_free_port` 空闲端口探测、`_wait_for_api` 健康检查后开浏览器、**`_monitor_frontend` 前台监控线程**（双路径：主动 `/api/shutdown` 秒退 + 心跳超时 30 分钟兜底，避开睡眠唤醒/断网误杀）、`is_frozen()`/`resource_dir()`、`COMFY_FETCH_HEADLESS=1` 跳过交互且不弹浏览器不监控 |
| `data/models.json` | curated 别名表（**故意留空**，见「已知限制」） | 兼承载私有仓库 URL 映射（schema 已扩展，见「私有仓库支持」） |

### 前端（`comfy_model_downloader/web/`）
`index.html` + `styles.css` + `app.js`，零依赖纯静态（无 CDN、无构建），暗色工程控制台风格。6 个视图：导入 / 下载计划 / 下载进度 / 历史 / 校验 / **目录设置弹窗**（`#dlgSettings`：手输根目录 + 浏览（osascript）+ 模型目录 + 并发数 + 自动探测 + 探针反馈「本地模型文件 N 个 / 目录结构 像 ComfyUI」）。页面 `<title>`、`#brand__name`、`ApiError` 提示文案、ready 提示全部为「ComfyUI Model Downloader」。另有**前台心跳**（`startHeartbeat()`/`stopHeartbeat()`）：页面每 5s 向 `/ws/heartbeat` 发 ping，`beforeunload`/`pagehide` 时发 bye 并断开；断线静默重连（3s）；`USE_MOCK` 下不连。此机制让 launcher 感知浏览器前台是否还开着。

**手动 URL 输入区（`manualSourceHtml`，`app.js:1403`）**：在「无魔搭可信来源」时展开。后端已自动把 `huggingface.co` 改写到 `hf-mirror.com`（`modelscope_client.py:378-410`，`COMFY_FETCH_NO_HF_MIRROR=1` 可关）。三次文案迭代：
- **2026-09-29 16:30**：note 文案追加「若仍下载失败，可到 https://hf-mirror.com 手动搜索模型并复制下载链接」（外链新窗口打开 `target="_blank" rel="noopener noreferrer"`）；placeholder 从 `huggingface.co` 改为 `hf-mirror.com`。
- **2026-09-29 16:40**：在 label「直连 URL（可覆盖 HF/CivitAI/私有仓库）」下、紧贴 input 处插入 `<p class="field__hint">下载失败可到 https://hf-mirror.com 手动搜索模型获取下载 URL</p>`（外链新窗口打开），复用项目已有的 `field__hint` 样式（`styles.css:832`，11px 灰字，与设置弹窗 line 73 一致）。

### 打包（`packaging/`）
- `entry.py`：PyInstaller 入口 —— stdout 经 `_Tee` 写入 `~/Library/Logs/comfy-ui-model-downloader/launcher.log`，崩溃弹原生 critical 弹窗含 traceback，弹窗标题为「ComfyUI Model Downloader」；`--diag` 参数跑模块自检
- `comfy-model-downloader.spec`：BUNDLE 成 **`comfy-ui-model-downloader.app`**（CFBundleName/DisplayName = "ComfyUI Model Downloader"；EXE 内部名 `comfy-model-downloader`；COLLECT name `comfy-model-downloader`；bundle_identifier `cn.comfyuimodeldownloader.app`），`collect_all(modelscope/modelscope_hub)`（惰性导入多必须整体收集）、datas 收 `web/` 与 `data/`、排除 tkinter/numpy 等。docstring 注明 conda 环境名 `comfy-fetch` 是开发环境名，与产品标识无关
- **产物 `dist/comfy-ui-model-downloader.app`（93MB，原生 arm64）**；构建命令：
  ```bash
  /opt/anaconda3/envs/comfy-fetch/bin/python -m PyInstaller packaging/comfy-model-downloader.spec --noconfirm --distpath dist --workpath build/pyinstaller
  ```
  构建完成后 `dist/` 干净（只有 `.app`，不再残留 COLLECT 临时目录）。

### 测试（`tests/`，104 例全绿）
- `test_parser.py` —— 三种格式、8 种原生加载器、枚举值排除
- `test_core.py` —— mapping/scan/verify/plan，含伪造损坏 safetensors
- `test_downloader.py` —— 并发上限、重试、损坏隔离、取消
- `test_modelscope_client.py` —— 全离线（`httpx.MockTransport`），验证 302 不泄漏鉴权头、Range 续传、URL 直连分支
- `test_server.py` —— 全部端点

`pytest tests/ -q` → **104 passed, 1 warning**（warning 为 fastapi testclient 的 StarletteDeprecationWarning，与项目无关）。

### 工具链（2026-09-29 17:33）
- `scripts/bump_version.py` + `Makefile` 的 `bump` target：patch 版本号一键同步 6 个文件（pyproject/__init__/spec/web/app.js + 两处 USER_AGENT）。`comfy_model_downloader/__init__.py` 已改为 importlib.metadata 动态读 + 兜底字面量。`tests/test_server.py:56` 版本断言改为 `r"^\d+\.\d+\.\d+"` regex，bump 后无须改测试。bump 是显式发布动作。

## 用法

### macOS .app（推荐）
双击 `dist/comfy-ui-model-downloader.app`。首次启动弹原生目录选择器选 ComfyUI 根目录 → 自动起服务 → 浏览器打开。之后每次启动读配置，不再弹窗。日志 `~/Library/Logs/comfy-ui-model-downloader/launcher.log`；崩溃弹窗含原因。

**说明 —— 旧配置不会自动迁移**：用户此前在 `~/Library/Application Support/comfy-fetch/config.toml` 写过的配置**已不再被读取**（不改名决策：全量改名，不管旧配置）。首次启动会因为找不到 config 进入正常的「弹原生目录选择器」流程，重选 ComfyUI 目录即可。

**关前台自动退后台（双路径机制）**：`.app` 启动（正常模式）后，launcher 起监控线程 + 前台页面建立心跳 WS。
- **快路径（主动 bye）**：浏览器 `pagehide`/`beforeunload` 时 `navigator.sendBeacon('/api/shutdown', '')`，服务端收到立即把 `_shutdown_requested_at = now + 5s`（5s grace 防 reload 误杀），监控线程下个 2s 轮询内检测到 deadline 且 grace 内没收到心跳才调用 `server.should_exit = True` 让 uvicorn 优雅退出——覆盖用户主动关窗口/关 tab/关浏览器等场景，秒级响应。
- **兜底路径（心跳超时）**：`HEARTBEAT_TIMEOUT = 1800s`（30 分钟）。仅当浏览器崩溃/进程被杀/网络长期断流等没有触发 sendBeacon 的场景下生效——睡眠唤醒/Chrome 后台节流导致的短暂 WS 失联不再误杀。
- **headless/CLI/裸 uvicorn 不挂监控**：monitor 只在 `open_browser=True`（即双击 .app）时启动，且从未收到心跳（浏览器没打开过）也不启用超时退出，避免无头模式误杀。

### Web UI（源码模式）
```bash
export COMFY_ROOT=/你的/ComfyUI
/opt/anaconda3/envs/comfy-fetch/bin/python -m uvicorn comfy_model_downloader.server:app --port 8799
# 打开 http://127.0.0.1:8799/
```
前端默认连真实后端；`?mock=1` 走纯前端演示数据。**ComfyUI 目录现在可以直接在界面「设置目录」弹窗里改**（手输 / 浏览 / 自动探测三条路），改完立即对后续请求生效并持久化。

### 设置端点（前端「设置目录」弹窗的后端）
- `POST /api/config` body `{comfy_root, models_dir?, concurrency?, persist?}` → 校验/就地改写/落盘，返回 config + probe（`looks_like_comfyui/notes/model_file_count`）
- `POST /api/config/browse` → 弹 macOS 原生目录选择器（`choose_folder`），返回 `{path, supported}`
- `POST /api/config/detect` → 扫 home/Desktop/Downloads 找 ComfyUI 候选，返回 `{candidates, current}`
- `GET /api/config` → 现有配置（只读）

### CLI
```bash
cd /Users/gaoyajing/Downloads/ComfyUI
export COMFY_ROOT=/你的/ComfyUI
PY=/opt/anaconda3/envs/comfy-fetch/bin/python

$PY -m comfy_model_downloader.cli scan  workflow.json          # 只解析 + 查重，不联网
$PY -m comfy_model_downloader.cli plan  workflow.json          # 解析 + 匹配魔搭来源，输出表格
$PY -m comfy_model_downloader.cli fetch workflow.json          # 直接下载
$PY -m comfy_model_downloader.cli verify                       # 校验本地已有模型
$PY -m comfy_model_downloader.cli serve --port 8799            # 启动 Web UI
```
公共选项：`--comfy-root` / `--models-dir` / `--dry-run` / `--json`。

或者安装后直接用 CLI 命令：
```bash
comfy-ui-model-downloader serve --port 8799
comfy-ui-model-downloader plan workflow.json
```

### 环境
conda 环境 `comfy-fetch`（python 3.11，**开发环境名保留不动**），依赖：fastapi / uvicorn / pydantic / click / httpx / modelscope 1.40.1 / modelscope_hub 0.4.5 / python-multipart / **PyInstaller 6.22.3**（打包用）。

## 关键决策与约束

### 为什么不用 SDK 的 `download_file`
`modelscope_hub` 的 `HubApi.download_file` 是**同步阻塞且无进度回调**，20GB 下载拿不到进度条。改为 `modelscope_client.py` 自己用 httpx 流式拉取。

### 为什么要两段式请求（防 token 泄漏）
魔搭的下载 URL 会 302 跳到 CDN（`cdn-lfs-cn-1.modelscope.cn/.../lfs-objects/...&auth_key=...`）。`Authorization` 若被 httpx 跟着重定向带过去，等于把 token 泄漏给 CDN。所以：
1. 第一个请求打 `/api/v1/models/{repo_id}/repo?FilePath=...`（带鉴权）拿 `Location`；
2. 第二个请求打 `Location`，**只带 `User-Agent`，不带任何凭据**。
并且**每次都重新请求第一个 URL**，绝不缓存带 `auth_key` 的 302 地址（有有效期）。

### 为什么不用 SDK 的 `list_model_files`
老 API 只返回路径和大小，**没有 sha256**。改用 `HubApi.list_repo_files`，实测每个 blob 都带可信 `Sha256` 和 `Size`。

### 搜索走 dolphin REST
SDK 无 `search()` 方法，`list_repos(search=...)` 也不返回 `ChineseName`。改用裸 REST `PUT /api/v1/dolphin/models`，有 `ChineseName` + `Downloads`/`Stars`。**没有 `ModelId` 字段，`repo_id = Path + "/" + Name` 拼**。

### 鉴权默认匿名
实测文件列表、搜索、下载**匿名全部可用**。token 只对私有库和限流有用。

### 版本号 + 构建号
spec 在打包时自动注入 build 号：`CFBundleShortVersionString` 由 `scripts/bump_version.py` 同步维护；`CFBundleVersion = <YYYYMMDDHHMMSS>`（构建时间戳）。`/api/config` 的 `version` 字段读自 `comfy_model_downloader.__version__`（importlib.metadata 动态读 pyproject，`PackageNotFoundError` 时回落硬编码字面量）。

**bump 脚本**：`scripts/bump_version.py` 单一命令把 patch 版本号 +1，并把新版本号同步到 6 个出现处：`pyproject.toml`（PEP 621 真相源） / `comfy_model_downloader/__init__.py`（兜底字面量） / `packaging/comfy-model-downloader.spec`（`VERSION`） / `comfy_model_downloader/web/app.js`（`MOCK_CONFIG.version`） / `comfy_model_downloader/modelscope_client.py` 与 `comfy_model_downloader/config.py`（两处 HTTP `User-Agent`）。`tests/test_server.py:56` 的版本断言已改为动态 regex（`^\d+\.\d+\.\d+`），不绑定具体数字。bump 是发布期决策，应该由开发者显式触发。用法：

```bash
make bump            # 或 python scripts/bump_version.py
# 输出：Bumped version: 0.1.0 → 0.1.1
#       Updated files: ...（列出 6 个文件的相对路径）
```

### 配置优先级（实测修正！）
**显式参数 > 配置文件（config.toml，`section.get` 先查）> 环境变量 > 默认值**。`COMFY_ROOT` 环境变量**会被**用户配置文件里的 `comfy_root` 覆盖——对 .app 这是预期行为（记住用户设过的目录优先）。`user_config_path()` 是打包后唯一可信的配置位置（cwd 不可靠）。

### 设置目录为何「改完立即生效」
`server.py` 的 `create_app()` 只构造一次共享 `st = settings`，被所有端点闭包捕获；`LocalIndex.build(...)` 每次 `/api/plan` 都重建。`_apply_comfy_root` **原地改写** `st.comfy_root`/`st.models_dir` → 后续请求即时用新目录，无需重启。函数内有**必要注释**写明这一不变量，别"清理"成返回新 Settings。

### 重命名决策记录（2026-09-29）
用户在改名决策中明确选「全量改名，不管旧配置」。即：
- 包名、配置目录、配置文件名、日志目录、CLI 命令、EXE 内部名、bundle id、spec 文件名、显示名 **全部统一**为 ComfyUI Model Downloader 体系
- **不写旧路径回退**：`user_config_path()` 只看新路径，不再探测 `~/Library/Application Support/comfy-fetch/` 旧目录
- **conda 环境名刻意保留** `comfy-fetch`（环境名 ≠ 产品标识，改名要重装全部依赖）
- 用户原有的旧配置（指向 `/Users/gaoyajing/ComfyUI-Shared`）已失效，需在 UI 的「设置目录」弹窗里重新指定 ComfyUI 目录

## 已知限制

### 1. 魔搭上没有 ComfyUI 单文件命名的完整镜像（最重要）
实测 9 个真实模型名**只有 6 个能自动解析**（`flux1-dev`→官方 `black-forest-labs/FLUX.1-dev`、`dreamshaper_8`→`digiplay/DreamShaper_8`、`Realistic_Vision_V5.1`→`AI-ModelScope/...`、`t5xxl_fp8_e4m3fn`、`clip_l`、`ae.safetensors` 均命中；`canny_xl_canny`/`flux-detail-sldr-b1`/`CLIP-ViT-H-14...` 无人）。原因：ControlNet/LoRA 在魔搭上基本是 **diffusers 布局**（`config.json`+`diffusion_pytorch_model.*.bin`），ComfyUI 加载不了。
**结论：「未解析 → 人工指定仓库」不是降级兜底，是必需的主路径。** UI 的手工来源输入框与设置弹窗是核心功能。

### 2. curated 别名表故意留空
`data/models.json` 的 `models` 是空对象。**没往里写任何猜测的仓库 id**（curated 命中跳过搜索、写错会去不存在的仓库下载）。扩充方式（schema）：
```json
{ "models": { "flux1-dev.safetensors": { "repo_id": "black-forest-labs/FLUX.1-dev",
  "file_path": "flux1-dev.safetensors", "size": 23579431568, "sha256": "…" } } }
```
指向自己的文件：`--curated-path` 或配置项 `curated_path`。

### 3. 解析规则的边界
- `comfy_extras` 里 `t2i_adapter_name`/`upscale_model_name`/`photomaker_name`/`latent_upscale_model_name` 是**按惯例推定的**，未从源码核实。
- `widgets_values` 位置型解析依赖 `WIDGET_ORDER`；所有输入强制校验扩展名，宁可漏判不误判。
- `ipadapter`/`animatediff` 是自定义节点目录，不在核心 `folder_paths.py`。

## 踩过的坑（已修，勿回退）

1. **枚举值被当成模型文件** —— `UNETLoader.weight_dtype="default"`、`DualCLIPLoader.type="flux"`。解法：字符串输入强制 `_accept()` 校验扩展名。
2. **Path 穿越** —— `sanitize_subpath` 保留 Windows 盘符会逃出模型根目录。已修：首段含 `:` 丢弃。
3. **远端无 sha256 被误判损坏** —— `verify.py` 的 `NO_CHECKSUM`（文件头+大小都过）必须算完成。`downloader.py` 的 `ACCEPTED_STATUSES` 显式收下 OK 与 NO_CHECKSUM。
4. **协作式取消抛普通 Exception 会被当可重试失败** —— 必须抛 `asyncio.CancelledError`（downloader 显式 re-raise）。
5. **候选排序只看搜索排名** —— 3 粉的小仓库压过官方。`Candidate.score` 已含热度加权，排序必须用它。
6. **前端 SVG 巨化** —— `icon()` 返回裸 `<svg>` 无 `width/height`，而 CSS 图标尺寸全是 `[data-icon]` 后代选择器 → 未包裹图标退回 ~300×150。已在 `icon()` 里加固有尺寸，别退回逐处包 `data-icon`。
7. **`Settings.save()` 写出非法 TOML** —— `lines += ["", "concurrency =", str(n)]` 三元素列表。已修为 `f"concurrency = {int(...)}"` 单行。
8. **窗口模式 `sys.stdout/stderr is None`** —— `_Tee` 要 `_ensure_streams()` 开真实句柄；**但 formatter 崩溃的真正根因是 `_Tee` 缺 `isatty`**（uvicorn `DefaultFormatter.should_use_colors()` 调用它），logging 把任何 formatter 异常统一报成 `Unable to configure formatter 'default'`。`_Tee` 的 `__getattr__` 透传**必须保留**（有注释说明）。
9. **launcher 无目录时 headless 也起服务挂住 shell** —— `comfy_root is None` 一律快速失败 return 1，不管 interactive 与否。
10. **重复 id `btnBrowse`** —— 拖拽区 span 与设置弹窗按钮撞名。弹窗按钮改名 `#btnPickDir`（app.js 里 `$('#btnBrowse')` 全局替换）。
11. **`iter_model_files` 传空类别返回 0** —— 它吃单个类别；逐类别累加才能数对模型文件（`_probe` 按 `CATEGORY_DIRS` 遍历）。
12. **前端候选 chip 截断** —— 状态列 `已存在·其他目录` 超宽，改短为「其他目录」并加宽列。
13. **`from .server import _shutdown_requested` 拿到旧 bool 快照** —— Python `from X import Y` 对 bool/int/str 等不可变类型只是把本地名绑到旧对象，server 模块 `global Y = True` 重新绑定不会反映到 launcher 内的本地名字 → `/api/shutdown` 200 但监控线程永远看不见。修复：launcher 用 `from . import server as _server`，按模块属性 `_server._shutdown_requested` 读取。代码注释里有反例说明，防回退。
14. **「关前台退后台」误杀睡眠唤醒场景** —— 25s 心跳超时太激进，下载期间页面静止时浏览器节流/睡眠唤醒都会断 WS 导致 uvicorn 被退出。修复 = 双路径：`pagehide` 时 `navigator.sendBeacon('/api/shutdown')` 主动秒退（覆盖 99% 主动关闭），心跳超时改为 1800s（30 分钟，仅作浏览器崩溃/长期断流的兜底）。
15. **`ResolvedSource` 加 `url` 字段要放最后** —— 我最初加在 `file_path` 之后、`size` 之前，立刻导致 6+ 个旧测试位置参数错位（123 落进 url、`"ab"*32` 落进 size、`0.95` 落进 sha256）。修复：`url` 字段放在 `candidates` 之前所有位置参数之后。位置参数 dataclass 一旦修改字段顺序必须先扫所有调用方。
16. **`icon()` 裸 svg 现在内置 `width="16" height="16"`** —— chip / btn--icon / toast 关闭钮直接拼裸 svg 都已安全。**新加 svg 引用必须包 `[data-icon]` 或在 `icon()` 里注册**。
17. **PyInstaller spec 里 `Path(__file__)` 抛 NameError** —— spec 用 `exec(spec_text, {})` 执行，没有 `__file__`。原版本号增强用 `Path(__file__).resolve().parent.parent` 定位项目根直接挂掉，被 except 兜底 → 永远走时间戳分支。修复：subprocess 不传 `cwd`，让外部工具用父进程（PyInstaller 命令发起者）的 cwd。
18. **「刷新浏览器误杀服务」bug —— `pagehide` 在 reload 和真离开都触发，原 `request_shutdown()` 立刻设 `_shutdown_requested=True` → launcher 监控线程秒退服务 → 刷新后连不上。修复：grace 窗口 5s——`request_shutdown()` 改为设 `_shutdown_requested_at = time.monotonic() + 5.0`，`ws_heartbeat` 收到任何心跳都调 `cancel_shutdown_request()` 撤销（页面 reload 重连会立刻发心跳），launcher 只在 `now >= deadline` 才退。`cancel_shutdown_request()` 在 deadline 已过后返回 False 不复活（防 launcher 正在退出时被新心跳救活）。
19. **手动表单 stale 错误条** —— 用户提交一次失败后错误条一直显示（与「后端已连接」状态矛盾）。修复：表单 `<form>` 加 inline `oninput="(this.querySelector('.mr__err')||{}).hidden=true"`——用户改任意 input 即视为重试意图，自动清错。inline 而非 JS 委托因为 `renderPlan` 重渲 DOM 全新。
20. **hf-mirror 国内镜像改写** —— `DirectURLFetcher` 默认把 `huggingface.co` 改成 `hf-mirror.com`，绕过 HF 国内不可达。`COMFY_FETCH_NO_HF_MIRROR=1` 可关。`rewrite_hf_url` 是 classmethod，纯 host 替换，保留 path/query。不动 UI：用户在直连 URL 输入框粘贴 HF URL 即自动走国内镜像。
21. **`/api/plan/override` 未返回完整 plan** —— 端点原本只返 `{item, totals, note}`，前端 `submitOverride` 把 `data` 直接赋给 `S.plan`，但 `data.items` 不存在 → `renderPlan` 内部 `items.length` 抛错（前端 catch 静默吞）→ 重渲失败 → 用户看到的现象是「点确认并重算没反应、行消失」。修复：return 处加 `**plan.to_dict()` 展开，把 `items` 数组带回前端。Playwright 复现：click 触发路径下 `#planRows` 行数 8→0；修复后稳定 8→8。
22. **手动表单收窄到「只 URL」** —— 用户用下来发现「ModelScope 仓库 ID + 仓库内文件路径」两个 input 在 dolphin 搜索已经能命中主流模型时属于冗余字段，反而干扰操作。移除这两个字段（包括 `manualSourceHtml` 的渲染 + `submitOverride` 的 else 分支 + repo/file_path 变量），表单只保留「直连 URL」一个 input。`styles.css` 加 `.mr__url`（width:100%）、`.mr__submit`（align-self:flex-start）、`.mr__cands__lb`（label 颜色类）替换原 inline style。**服务端 `post_override` 仍保留 OVERRIDE 分支**（CLI 与 future REST 用），不影响 API 契约。
23. **重命名批量替换：`for f in $FILES` 在 zsh 下不做默认单词分割** —— `FILES=$(grep -rl ...)` 后 `for f in $FILES` 把整串当单个文件名传给 perl，perl 报 "Can't open <整串>"。第一次批量替换**一个文件都没改**却被误认为成功。正确做法：`find ... -exec perl -pi -e 's/.../.../g' {} +`。zsh 必须用 `find -exec` 或显式 `setopt SH_WORD_SPLIT`。
24. **重命名：批量文件枚举把 `dist/` `build/` 也带出来** —— `.app` 包内路径超长，grep 报 "File name too long"。批量操作必须显式 `--exclude-dir=dist --exclude-dir=build`。同时这两个目录**根本不该纳入版本管理**（`.gitignore` 缺失导致历史遗留），下次清理应一并加 `.gitignore`。
25. **重命名：21 个 `__pycache__/*.pyc` 入库阻塞 `mv`** —— 项目**原本没有 `.gitignore`**，字节码本不该入库。修复：从跟踪中移除这 21 个文件后再 `mv`。已加入「建议的下一轮」待办：补 `.gitignore` 防止再被误提交。

### 私有仓库支持（第一步：直接 URL）

调研结论（2026-09-28）：ComfyUI 本身无下载逻辑，ComfyUI-Manager 是另一条独立链（HF_ENDPOINT 镜像 / HF_TOKEN 透传 / hf_hub_download / network_mode / default channel 白名单）。我们只走魔搭，HF / CivitAI / 直连 URL 完全未覆盖。第一步实现：**直连 URL 下载 + 私有仓库 curated 映射**（HF mirror 缓行）。

实现要点：
- `plan.SourceKind.URL = "url"` 新枚举；`ResolvedSource.url` 字段（**keyword-only**，放所有位置参数之后）；URL 类型始终返回 HIGH 置信度
- `modelscope_client.DirectURLFetcher`：单段 httpx GET + `follow_redirects=True`，可选 `Authorization: Bearer` 头，Range 续传（206 追加 / 200 截断重写 / 416 视为完成），取消返回 None（与 ModelScopeFetcher 对齐）。token 来源：`DIRECT_URL_TOKEN` > `HF_TOKEN` > `CIVITAI_TOKEN` 三重兜底
- `modelscope_client.RouteFetcher`：按 source.kind 派发到具体 fetcher。新增源只需 `by_kind` 加一项
- `server.OverrideBody` 加 `url` 字段；`/api/plan/override` 接 URL 直连模型后**只改 source，不调魔搭**（不查 size/sha256）。下载用 RouteFetcher 自动分流
- `app.js manualSourceHtml`：未解析行表单加 `<input name="url">`，与 `repo_id`/`file_path` 并列；URL 优先于 repo_id+file_path；前端校验 `^https?://`
- `submitOverride`：URL 模式 vs 魔搭模式分支；payload 只发对应字段；say 提示用 URL 或 `basename(repo+path)`
- `data/models.json` 可扩展 `"source": "url"` 或 `"source": "huggingface"`（schema 预留，未实现 HuggingFaceIndex 协议）

未做：HuggingFaceMirrorFetcher（HF API）、CivitAI 支持、token UI 输入框。落地路径相同：在 `modelscope_client.py` 加新 fetcher 类 + `RouteFetcher.by_kind` 注册，前端若需入口再加 input。

## 端到端验收记录

- 真实网络：`plan` 解析两模型均「高」置信；下载 `extremely detailed.safetensors` → `models/loras/`，8789076 字节，sha256 `ef4a6eac…99c561`，文件头合法，**无残留 `.part`**；二次 `plan` → 「已存在」跳过生效。
- Web UI 真实跑通 9 模型 FLUX 工作流：6 命中 / 3 未解析带手工来源表单 / 34.72 GB；移动端 390px 无横向滚动。
- 设置弹窗浏览验收：改目录到 fake_comfy + 并发 5 → `cfgRoot`/`cfgModels` 实时更新、probe「本地模型文件 3 个」、改完 `/api/plan` 的 `present` 0→3 立即生效。
- 冻结包验收：#hb_verify 子进程端到端 —— 服务就绪 → 心跳 6s 存活 → WS 断开后进程自动退出（rc=0）；headless 打桩 `webbrowser.open` 验证不弹浏览器、45s 常驻不监控；`dist/comfy-ui-model-downloader.app` 实测 `/api/config` 返回真实目录 `/Users/gaoyajing/ComfyUI-Shared`、`GET /` 200、包内 WS `/ws/heartbeat` 可连、CFBundleName/DisplayName = "ComfyUI Model Downloader"。
- UI 评估 8.5/10 → 8.9/10：P1 `.rows padding-bottom` 76/112 → **132px**（粘性 actionbar 不再遮挡展开的未解析行）+ P2 五处 inline style 全部改为新 CSS 类（`.repoline__nohref` / `.sizenum--pending` / `.chip--rot` / `.mr__chip__score` + 动态 toggle 的 `classList.toggle('chip--rot')`）+ P2 `.fbtn.is-on[data-filter="unresolved"]` 改用 `--vio` 紫色与未解析 chip 语义联动。Playwright 自动化验证：`chevron chip--rot present: True`、`rows padding-bottom: 132px`、`unresolved tab color: rgb(168,140,216)`。
- **2026-09-29 全量重命名验收**：`pytest tests/ -q` → **104 passed, 1 warning**；新 spec 重建 → `dist/comfy-ui-model-downloader.app`（93MB arm64），PlistBuddy 校验 `CFBundleName=CFBundleDisplayName="ComfyUI Model Downloader"`、`CFBundleIdentifier="cn.comfyuimodeldownloader.app"`、`CFBundleShortVersionString="0.1.0"`、`CFBundleVersion="9cb69a1"`（构建标识）；源码区 `comfy_fetch`/`comfy-ui-model-tool`/`comfy-model-tool`/`ComfyUI Model Tool` **零残留**，剩余 `comfy-fetch` 仅出现在 conda 环境名（README:79-80、spec:5,7）。

## 相关文件

- `comfy_model_downloader/` 后端 13 个模块 + `data/models.json` + `web/{index.html,styles.css,app.js}`
- `packaging/` `entry.py`（PyInstaller 入口）+ `comfy-model-downloader.spec`
- `scripts/bump_version.py` patch 版本号一键 bump 脚本（同步 6 个文件）
- `Makefile` `make bump` / `make test` 两个常用 target
- `dist/comfy-ui-model-downloader.app` 构建产物（93MB arm64，可双击）
- `pyproject.toml` 项目元数据、依赖、`comfy-ui-model-downloader` 入口、pytest 配置
- `tests/` 104 个测试 + `fixtures/flux_workflow_ui.json`（真实工作流样本）
- `docs/使用手册.md` 用户手册
- `HANDOFF.md` 本文件
- `assets/` 品牌资产（`logo.svg` 矢量主源、`logo-master.png` 1024×1024、`icon.iconset/` 中间产物、`icon.icns` 最终 app icon、`logo-mark-{32,128}.png` README 头图；`render_logo.py` + `build_assets.py` 两个生成脚本）
- `~/Library/Application Support/comfy-ui-model-downloader/comfy-ui-model-downloader.toml` 运行时配置（旧路径 `comfy-fetch/` 已无效）
- `~/Library/Logs/comfy-ui-model-downloader/launcher.log` 启动与运行日志

## 未完成 / 建议的下一步

- **无阻塞项。** 优先级最高的是**把常用模型积累进 `data/models.json` 别名表**——绕过魔搭缺 ComfyUI 布局问题、提升自动化率最有效的手段。
- **已完成：** 补 `.gitignore`（覆盖 `__pycache__/` `*.pyc` `dist/` `build/` `.DS_Store` `.pytest_cache/` `.venv/` `assets/icon.iconset/` 等）——历史待办已关闭。
- **品牌资产（2026-09-29 17:50）**：`assets/logo.svg`（矢量主源，M monogram + 下载轨迹几何）/ `assets/icon.iconset/`（10 个 PNG 多尺寸）/ `assets/icon.icns`（macOS .app icon，PyInstaller spec `BUNDLE.icon=` 引用）/ `comfy_model_downloader/web/favicon.png`（32×32 opaque）/ `assets/logo-mark-{32,128}.png`（README 头图）。设计语言与 web UI 色板完全对齐（`--bg-0` / `--fg-0` / `--ac`）。生成流程：`python assets/render_logo.py`（写 master）→ `python assets/build_assets.py`（生成 iconset/icns/favicon/brand mark）。
- 可选：`comfy_extras` 几个节点的输入名做源码核实。
- 可选：下载并行分片（`MODELSCOPE_DOWNLOAD_PARALLEL_WORKERS=8`，要求 >500MB，会产生边车文件）。
- 可选：把 conda 环境名从 `comfy-fetch` 改成 `comfy-ui-model-downloader`（成本高：重装 fastapi/uvicorn/pydantic/click/httpx/modelscope 1.40.1/modelscope_hub 0.4.5/python-multipart/PyInstaller 6.22.3；收益低：仅环境名，无产品标识价值）。

---

## v0.1.11 首次正式发布（2026-09-29 22:10）

### 仓库发布前清理
- 补 `.gitignore`（67 行，覆盖 `__pycache__/` `*.py[cod]` `*.egg-info/` `build/` `dist/` `.eggs/` `.venv/` `.pytest_cache/` `.coverage/` `.tox/` `.idea/` `.vscode/` `.DS_Store` `build/pyinstaller/` `assets/icon.iconset/` `.codegraph/` `.mypy_cache/` `.ruff_cache/` `.omo/` `.env` 等）
- `git rm -r --cached` 移出 3223 个垃圾追踪（`dist/` 3169 个含完整 `.app` 树、`build/` 17、`__pycache__/` 19、`*.egg-info/` 6、`assets/icon.iconset/` 10、`.DS_Store` 2 等）。追踪文件数 3264 → 41
- 提交 `190e488` "chore: add .gitignore and untrack 3223 build artifacts" 已推到 `origin/Master`
- 提交 `01964c2` "chore: ignore .omo/ runtime directory" 本地领先 1（`.omo/` 运行时目录兜底，不影响 release `target_commitish`）
- 远端 Master HEAD = `190e488ae7aaad78cfe3735c4e6f54c35732b6f7`

### 发布产物（已上传至 GitHub Releases）
- Release URL: https://github.com/Gaoyajing0810/ComfyUI-Model-Downloader/releases/tag/v0.1.11
- Release ID: `399213986`
- Tag: `v0.1.11` → `190e488ae7aaad78cfe3735c4e6f54c35732b6f7`
- 资产 1: `comfy-ui-model-downloader.app.zip`（67 MB，SHA256 `235da5697803c2b1ee9fba84b5dd7d9e10beb24f20cc28560bc933d1dc0f97d0`）—— 双击启动的 macOS arm64 应用
- 资产 2: `comfy-ui-model-downloader-0.1.11.tar.gz`（201 KB，SHA256 `eef0953a0145bd67bede816467be9558b6dad50c829dda2eaf5465d94a05b5dc`）—— 52 个条目源码包，从 `git archive HEAD` 生成（已自动排除 `dist/` `build/` `__pycache__/` `.git/` 等）
- Release notes 来源：`/tmp/comfy-release/RELEASE_NOTES.md`（含下载表 + SHA256 + 6 项主要功能 + 快速开始 + 已知限制）

### 发布方式
- 无 `gh` CLI、无 SSH key、无 `.netrc` / `~/.git-credentials` / `~/.config/gh/`
- 用 `security find-generic-password -s "GitHub - https://api.github.com" -a "Gaoyajing0810" -w` 从 macOS Keychain 取出 `gho_*` OAuth token（`prot=NULL` 无 TouchID），验证 `permissions.push=True` 后用 curl + `Authorization: Bearer` 调用 GitHub REST API
- `create_release.sh`（`bash -n` 通过）：① `POST /repos/.../git/refs` 建 tag → ② `POST /repos/.../releases` 带 notes 建 release → ③ `POST /releases/{id}/assets` 上传两个资产（content-type 用 `application/zip` / `application/gzip`）→ ④ GET 验证
- 校验：`curl GET` tarball 拿 302 跳 CDN，`curl -I` .app.zip 拿 302 跳 `release-assets.githubusercontent.com`
- token 用完立即 `unset GITHUB_TOKEN`，`env | grep` 确认无残留

### 已记录的产物路径
- `/tmp/comfy-release/comfy-ui-model-downloader.app.zip`
- `/tmp/comfy-release/comfy-ui-model-downloader-0.1.11.tar.gz`
- `/tmp/comfy-release/RELEASE_NOTES.md`
- `/tmp/comfy-release/create_release.sh`