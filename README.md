<div align="center">

<img src="assets/logo-mark-128.png" alt="ComfyUI Model Downloader" width="96" height="96">

# ComfyUI Model Downloader

**把 ComfyUI 工作流丢进去，自动从魔搭（ModelScope）补齐缺失的模型**

[应用介绍](#这是什么) · [使用手册](docs/使用手册.md) · [命令行](#命令行参考) · [配置](#配置参考) · [CHANGELOG](CHANGELOG.md)

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![ModelScope](https://img.shields.io/badge/ModelScope-魔搭社区-FF6A00?style=flat-square)](https://www.modelscope.cn/)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey?style=flat-square)]()
[![Version](https://img.shields.io/badge/version-0.1.13-5CC8D8?style=flat-square)](https://github.com/Gaoyajing0810/ComfyUI-Model-Downloader/releases)
[![Tests](https://img.shields.io/badge/tests-pytest%20104%20passed-42a5f5?style=flat-square)]()
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

</div>

---

## 这是什么

打开一个 ComfyUI 工作流 JSON，通常会撞上一堆红色节点：

> `CheckpointLoaderSimple`: value not in list —— 缺 checkpoint
> `LoraLoader`: value not in list —— 缺 lora
> `VAELoader`: value not in list —— 缺 vae

**ComfyUI Model Downloader** 读你的工作流，把所有模型引用逐个解析出来，判断该去 ComfyUI 的哪个子目录，在模型社区找到对应文件，下载、校验、落盘到位。下载完直接回 ComfyUI 刷新模型列表，工作流就能跑了。

### 它解决的三件事

| 痛点 | 传统做法 | 本工具 |
|---|---|---|
| 不知道缺哪些模型 | 一个个红节点点开看 | 一次列出全部引用，标注哪些已有、哪些缺失 |
| 不知道去哪找模型 | 在 HuggingFace 到处搜 | 自动匹配模型社区，展示仓库与匹配置信度 |
| 不知道放哪个目录 | 查 ComfyUI 文档试错 | 按节点类型自动判定子目录，落盘即用 |

### 特性

- **工作流即输入** — 拖入 `.json` 即可，兼容 API 格式与 UI 格式（含 `widgets_values` 位置型解析）
- **零重复下载** — 扫描本地 25 个模型类别，已存在的直接跳过
- **完整性校验** — 下载后校验大小与哈希，损坏文件不会混进模型目录
- **自动归类** — 按 `class_type` → 输入名 → 文件名三级规则判定目录，认得 20+ 类模型
- **断点续传** — 中断后重新执行可继续未完成的文件；URL 412 Range 校验防止截断文件被错误接受
- **两种用法** — 图形界面（双击 `.app`）或命令行，功能完全一致
- **.app 自动退出** — 双击启动后台服务，关掉浏览器即自动关闭，无需手动管理
- **直链补全** — 遇到魔搭无收录的模型，可粘贴 HF/CivitAI 直链下载（host 白名单 + https-only + 凭证作用域保护）
- **下载可取消** — UI 取消按钮真的调 server 取消，不会假阴性假象
- **Conventional Commits + SemVer + CHANGELOG 自动化** — 见 [开发流程](#开发流程)

### 架构

```
工作流 JSON
    ↓  parser.py        解析节点与模型引用
    ↓  mapping.py       class_type / 输入名 / 文件名 → 模型类别
    ↓  scan.py          扫描本地 models/，标记 已存在 / 缺失 / 损坏
    ↓  resolver.py      在模型索引中匹配可信来源
    ↓  downloader.py    并发下载 + 断点续传
    ↓  verify.py        哈希与大小校验
落盘到 ComfyUI 模型目录
```

> 本工具**不依赖 ComfyUI 本体运行**，规则表已对照 ComfyUI 官方 `folder_paths.py` 与 `nodes.py` 核实，可在未部署 ComfyUI 的机器上独立使用。

---

## 快速开始

### 环境要求

- Python 3.10 或更高
- 一个 ComfyUI 安装目录（含 `models/`）
- 魔搭账号（仅需公开模型时无需登录）

### 从源码运行

从 GitHub Release 下载源码压缩包，解压后进入目录：

```bash
cd comfy-ui-model-downloader

# 建议使用独立虚拟环境
conda create -n comfy-fetch python=3.11 -y
conda activate comfy-fetch

pip install -e .

# 启动图形界面
comfy-ui-model-downloader serve
```

浏览器会自动打开 `http://127.0.0.1:8188`。

### 从零开始

```bash
# 1. 先看看工作流缺什么（只读，不联网）
comfy-ui-model-downloader scan workflow.json --comfy-root ~/ComfyUI

# 2. 生成下载计划（联网匹配来源，不下载）
comfy-ui-model-downloader plan workflow.json --comfy-root ~/ComfyUI

# 3. 确认无误后执行下载
comfy-ui-model-downloader fetch workflow.json --comfy-root ~/ComfyUI
```

---

## 使用手册

> 完整图文步骤见 **[docs/使用手册.md](docs/使用手册.md)**。

### 图形界面五步走

```
① 导入工作流  →  ② 下载计划  →  ③ 开始下载  →  ④ 校验
```

**① 导入工作流** — 把 `.json` 拖进页面，或点选文件。工具会立即解析，列出该工作流引用的全部模型、每个模型的落盘位置、当前本地状态。

**② 查看下载计划** — 匹配魔搭来源后的对照表：

| 本地状态 | 含义 | 默认动作 |
|---|---|---|
| `已存在` | 文件在正确目录且完整 | 跳过 |
| `其他目录` | 同名文件在别的类别目录 | 需人工确认 |
| `缺失` | 本地没有 | 待下载 |
| `损坏` | 存在但哈希不匹配 | 重新下载 |

来源列显示命中的魔搭仓库与置信度。置信度低的条目会列出候选，由你决定。

**③ 开始下载** — 底部显示「N 项待下载 · 合计 X GB」，确认后点击开始。下载页实时显示每个文件的进度、已下载量与总量。

**④ 校验** — 独立页面，扫描全部本地模型文件，列出损坏或异常项。

### 界面导航

| 标签 | 用途 |
|---|---|
| 导入工作流 | 上传解析工作流，查看模型引用与本地状态 |
| 下载计划 | 复核匹配结果，手工改源或剔除条目 |
| 下载 | 实时进度、服务端日志、取消任务 |
| 历史 | 过往任务记录 |
| 校验 | 全量扫描本地模型完整性 |

### 常见问题

<details>
<summary><b>提示「未指定 ComfyUI 根目录」</b></summary>

点顶部「设置目录」，或用环境变量：

```bash
export COMFY_ROOT=~/ComfyUI
```
</details>

<details>
<summary><b>某模型显示「未找到可信来源」</b></summary>

模型社区没有收录该文件。可在下载计划页手工指定其他来源 URL，或从 ComfyUI Manager 等渠道手动下载后放入对应目录。
</details>

<details>
<summary><b>下载很慢或频繁重试</b></summary>

调低并发数，避免触发服务端限流：

```bash
comfy-ui-model-downloader fetch workflow.json --concurrency 1
```

或在设置中把并发改为 `1`。
</details>

<details>
<summary><b>文件校验失败</b></summary>

通常是下载不完整或磁盘写入错误。删除该文件重新下载即可，工具支持断点续传，不会丢失其他已完成的部分。
</details>

---

## 命令行参考

所有命令都支持 `--json` 输出，便于脚本化。

### `scan` — 查看本地状态

解析工作流并对照本地模型，**不联网、不下载**。

```bash
comfy-ui-model-downloader scan workflow.json --comfy-root ~/ComfyUI
```

### `plan` — 生成下载计划

联网匹配来源，输出计划但**不下载**。

```bash
comfy-ui-model-downloader plan workflow.json --comfy-root ~/ComfyUI
comfy-ui-model-downloader plan workflow.json --offline      # 跳过来源匹配
```

### `fetch` — 执行下载

解析 → 匹配 → 下载 → 校验，一条龙。

```bash
comfy-ui-model-downloader fetch workflow.json --concurrency 5
comfy-ui-model-downloader fetch workflow.json --dry-run      # 只打印将下载的条目
```

### `verify` — 校验本地模型

```bash
comfy-ui-model-downloader verify --comfy-root ~/ComfyUI
comfy-ui-model-downloader verify --category checkpoints --category loras
```

退出码：`0` = 全部正常，`1` = 存在问题。可直接用于 CI。

### `serve` — 启动 Web 界面

```bash
comfy-ui-model-downloader serve --port 8188
comfy-ui-model-downloader serve --reload                        # 开发模式
```

### 全局选项

| 选项 | 说明 |
|---|---|
| `--comfy-root PATH` | ComfyUI 根目录 |
| `--models-dir PATH` | 模型目录，默认 `<comfy-root>/models` |
| `--json` | 以 JSON 输出 |
| `-h, --help` | 查看帮助 |
| `--version` | 查看版本 |

---

## 配置参考

配置优先级：**显式参数 > 环境变量 > 配置文件 > 默认值**。

### 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `COMFY_ROOT` | — | ComfyUI 根目录 |
| `COMFY_MODELS_DIR` | `<root>/models` | 模型目录 |
| `MODELSCOPE_API_TOKEN` | — | 魔搭访问令牌，提升配额与命中率 |
| `COMFY_FETCH_CONCURRENCY` | `3` | 并发下载数 |
| `COMFY_FETCH_RETRIES` | `3` | 失败重试次数 |

### 配置文件

用户级配置（自动生成，**不会保存 token**）：

| 平台 | 路径 |
|---|---|
| macOS | `~/Library/Application Support/comfy-ui-model-downloader/config.toml` |
| Windows | `%APPDATA%\comfy-ui-model-downloader\config.toml` |
| Linux | `~/.config/comfy-ui-model-downloader/config.toml` |

```toml
# comfy-ui-model-downloader.toml
comfy_root = "/Users/you/ComfyUI"
models_dir = "/Users/you/ComfyUI/models"
concurrency = 3
retries = 3
timeout = 30.0
deep_verify = true
health_check_existing = true
allow_basename_match = true
```

| 键 | 默认 | 说明 |
|---|---|---|
| `concurrency` | `3` | 并发下载数，弱网建议调低 |
| `retries` | `3` | 单文件重试次数 |
| `timeout` | `30.0` | 单请求超时（秒） |
| `deep_verify` | `true` | 下载后做完整哈希校验，关闭可提速 |
| `health_check_existing` | `true` | 扫描时校验已存在文件，关闭可加快启动 |
| `allow_basename_match` | `true` | 允许跨目录按文件名匹配同名模型 |

> 图形界面下点击「设置目录」会自动写入 `comfy_root` 与 `models_dir`，无需手改文件。

---

## 魔搭 Token

公开模型无需 Token 即可下载。配置 Token 可以：

- 提高下载配额
- 访问私有仓库
- 提升匹配命中率

```bash
export MODELSCOPE_API_TOKEN=your_token_here
```

> Token 仅从环境变量或配置文件读取，**永��写入磁盘**。

---

## 开发

```bash
pip install -e ".[dev]"
pytest              # 运行测试
pytest -v tests/test_parser.py
```

### Bump 版本号 + Conventional Commits

本项目遵循 [Conventional Commits 1.0](https://www.conventionalcommits.org/) + [SemVer](https://semver.org/) + [Keep a Changelog 1.1.0](https://keepachangelog.com/) 三套标准。

#### 提交代码（推荐流程）

`scripts/commit.sh` 一站式：校验 conventional 格式 → 自动决定 bump → 同步版本号 → 写 CHANGELOG → git commit。

```bash
scripts/commit.sh "feat(server): add /api/cancel endpoint"      # → minor
scripts/commit.sh "fix(downloader): prevent zombie tasks"        # → patch
scripts/commit.sh "feat!: remove legacy auth"                     # → major
scripts/commit.sh --no-bump "docs: typo"                          # → 不 bump
scripts/commit.sh --amend                                        # 复用上次 msg
```

#### 手动 bump（不带提交）

```bash
make bump                            # 自动检测（默认 patch）
python scripts/bump_version.py --major
python scripts/bump_version.py --minor
python scripts/bump_version.py --patch --no-changelog    # 跳过 CHANGELOG
python scripts/bump_version.py --dry-run                 # 只打印
```

#### Type → Bump 映射

| type | bump | CHANGELOG 段 |
|---|---|---|
| `feat!:` / body `BREAKING CHANGE:` | **major** | Removed / ⚠️ BREAKING CHANGES |
| `feat:` | minor | Added |
| `fix:` | patch | Fixed |
| `refactor:` / `perf:` / `build:` | minor | Changed |
| `docs:` / `chore:` / `test:` / `ci:` / `style:` / `revert:` | 不 bump | — |

`bump_version.py` 从 `git log <last_tag>..HEAD` 解析前缀；找不到 last tag 时扫描全仓库 commits。
新版本号同步到 6 个位置：`pyproject.toml`（真相源）/ `__init__.py` / `spec` / 前端 `MOCK_CONFIG.version` / 两处 HTTP `User-Agent`。
`tests/test_server.py` 版本断言用 regex 不绑定具体数字，bump 后无需改测试。

#### CHANGELOG.md

每次 bump 自动在文件顶部插入新版本段（Keep a Changelog 1.1.0 格式），diff 链接指向 GitHub compare。
完整发布历史：[CHANGELOG.md](CHANGELOG.md)。

### 一键发布

```bash
make release         # = bump patch + PyInstaller 重打包 .app
make build           # 仅打包
```

详见 [v0.1.11](https://github.com/Gaoyajing0810/ComfyUI-Model-Downloader/releases/tag/v0.1.11) / [v0.1.12](https://github.com/Gaoyajing0810/ComfyUI-Model-Downloader/releases/tag/v0.1.12) / [v0.1.13](https://github.com/Gaoyajing0810/ComfyUI-Model-Downloader/releases/tag/v0.1.13) Release 页（含 SHA256 校验值）。

### 项目结构

```
comfy_model_downloader/
├── cli.py              命令行入口
├── config.py           配置加载（参数 > 环境变量 > 文件，原子写 TOML）
├── launcher.py         图形化启动器 + 前台心跳监控
├── server.py           FastAPI 服务（12 REST + WS /ws/heartbeat）
├── parser.py           工作流解析
├── mapping.py          模型目录映射规则 + safe_join 防 symlink 越界
├── scan.py             本地模型扫描（带 depth/files 上限）
├── resolver.py         魔搭来源匹配
├── modelscope_client.py 魔搭 API 客户端（含 search fallback + host 白名单 + 416 校验）
├── downloader.py       并发下载 + 断点续传 + retry
├── verify.py           完整性校验（size + sha256）
├── cleanup.py          启动 + 下载后清理陈旧 .part/.tmp/.download
├── plan.py             计划构建
└── web/                前端（原生 HTML/CSS/JS，无构建）

scripts/
├── bump_version.py     Conventional Commits → 自动 bump + 写 CHANGELOG
└── commit.sh           提交包装器（conventional 校验 + 自动 bump + commit）

tests/                  104 个 pytest 测试
docs/使用手册.md          图形界面 5 步走详细说明
CHANGELOG.md            版本变更日志
HANDOFF.md              会话交接 + 实施细节
```

---

## License

[MIT](LICENSE)

---

<div align="center">
<sub>ComfyUI Model Downloader · 从模型社区补齐 ComfyUI 模型</sub>
</div>
