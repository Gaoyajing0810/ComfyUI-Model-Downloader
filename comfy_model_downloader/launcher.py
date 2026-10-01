"""图形化启动器：供打包成 .app 后双击使用。

流程：读配置 → 缺 ComfyUI 目录则弹原生选择框 → 选空闲端口 → 起服务 → 开浏览器。
只依赖 macOS 自带的 osascript，无需 tkinter/PySide。
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from .config import Settings, user_config_path

_OSA_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

APP_NAME = "ComfyUI Model Downloader"
DEFAULT_PORT = 8799
STARTUP_TIMEOUT = 25.0
PROBE_INTERVAL = 0.25
HEARTBEAT_TIMEOUT = 1800.0
HEARTBEAT_POLL = 2.0


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """打包后静态资源在 bundle 内部，源码运行时在包目录。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def _osascript(script: str) -> str:
    """跑一段 AppleScript 并返回 stdout。stdin 断开，否则从 Finder 启动时会挂住。"""
    proc = subprocess.run(
        ["osascript", "-e", script],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def choose_folder(title: str, message: str) -> Path | None:
    """弹原生目录选择框。用户取消或非 macOS 时返回 None。"""
    if sys.platform != "darwin":
        return None
    script = (
        f'POSIX path of (choose folder with prompt {_as_applescript(message)} '
        f'default location (path to home folder))'
    )
    del title
    picked = _osascript(script)
    if not picked:
        return None
    return Path(picked).expanduser().resolve()


def _as_applescript(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError(f"osascript literal 必须是 str, 收到 {type(text).__name__}")
    if _OSA_CONTROL_RE.search(text):
        raise ValueError(f"osascript literal 含 ASCII 控制字符: {text!r}")
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def confirm(title: str, message: str) -> bool:
    """弹原生是/否确认框。"""
    if sys.platform != "darwin":
        return False
    script = (
        f'display alert {_as_applescript(title)} message {_as_applescript(message)} '
        f'buttons {{"取消", "好"}} default button "好"'
    )
    return bool(_osascript(script))


def notify(title: str, message: str) -> None:
    if sys.platform != "darwin":
        return
    _osascript(f'display notification {_as_applescript(message)} with title {_as_applescript(title)}')


def looks_like_comfyui(path: Path) -> tuple[bool, list[str]]:
    """粗判一个目录是不是 ComfyUI 安装目录，返回 (是否像, 提示信息列表)。"""
    notes: list[str] = []
    if not path.is_dir():
        return False, ["所选路径不存在或不是文件夹"]
    if (path / "models").is_dir():
        notes.append("找到 models/ 目录")
    else:
        notes.append("没有 models/ 目录")
    if (path / "main.py").is_file() and (path / "comfy").is_dir():
        notes.append("找到 main.py 与 comfy/，看起来是 ComfyUI 安装目录")
    elif (path / "comfy").is_dir():
        notes.append("找到 comfy/，看起来是 ComfyUI 安装目录")
    return bool(notes and notes[0].startswith("找到 models")), notes


def resolve_comfy_root(settings: Settings, *, interactive: bool = True) -> Path | None:
    """确保有可用的 ComfyUI 目录：先用现成的，否则弹窗问。"""
    if settings.comfy_root is not None and settings.comfy_root.is_dir():
        return settings.comfy_root

    if not interactive:
        return None

    notify(APP_NAME, "首次启动：需要选择你的 ComfyUI 安装目录")
    picked = choose_folder("选择 ComfyUI 目录", "请选择 ComfyUI 的安装目录（里面应该有 models 文件夹）")
    if picked is None:
        return None

    ok, notes = looks_like_comfyui(picked)
    _say("目录检查：" + "；".join(notes))
    if not ok:
        create = confirm("目录检查未通过", f"{picked}\n\n{chr(10).join(notes)}\n\n是否仍然使用该目录？")
        if not create:
            return None

    (picked / "models").mkdir(parents=True, exist_ok=True)
    settings.comfy_root = picked
    settings.models_dir = picked / "models"
    saved = settings.save()
    _say(f"已保存配置：{saved}")
    return picked


def find_free_port(preferred: int = DEFAULT_PORT, span: int = 40) -> int:
    for port in range(preferred, preferred + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_api(port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/api/config"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(PROBE_INTERVAL)
    return False


def _monitor_frontend(server, port: int) -> None:
    """前台监控：浏览器主动请求关闭（POST /api/shutdown）后立即退服务；
    心跳超时仅作兜底（覆盖浏览器崩溃/网络长期断流等场景）。

    只有收到过至少一次心跳（说明浏览器真的打开过页面）才启用超时退出，
    避免从未访问页面时误杀后台服务。
    """
    _say("前台心跳监控线程已启动")
    if not _wait_for_api(port, STARTUP_TIMEOUT):
        _say("前台心跳监控：等待服务就绪超时，监控失效")
        return
    # 按模块属性访问：_shutdown_requested_at 是 float，import 时拿到的是旧对象快照，
    # server.request_shutdown() 重新绑定模块全局不会反映到本地名字，会导致"快路径"永远不退出。
    from . import server as _server  # 延迟导入，与 create_app 同一时机
    _say("前台心跳监控：服务就绪，开始监听心跳")

    while not server.should_exit:
        time.sleep(HEARTBEAT_POLL)
        deadline = _server._shutdown_requested_at
        if deadline > 0 and time.monotonic() >= deadline:
            _say("前台请求关闭（倒计时已过），后台服务自动退出。")
            server.should_exit = True
            return
        last = _server.get_last_heartbeat()
        if last > 0:
            age = time.monotonic() - last
            if age > HEARTBEAT_TIMEOUT:
                _say("前台心跳长时间丢失（兜底超时），后台服务自动退出。")
                server.should_exit = True
                return


def launch(comfy_root: Path | None, port: int | None = None, *, open_browser: bool = True) -> int:
    """起服务并驻留。返回进程退出码。"""
    chosen_port = port or find_free_port()
    os.environ.setdefault("COMFY_FETCH_HOST", "127.0.0.1")
    if comfy_root is not None:
        os.environ["COMFY_ROOT"] = str(comfy_root)
    os.environ["COMFY_FETCH_PORT"] = str(chosen_port)

    _say(f"{APP_NAME} 正在启动 …")
    _say(f"  配置文件：{user_config_path()}")
    _say(f"  ComfyUI ：{comfy_root or '(未设置)'}")
    _say(f"  监听地址：http://127.0.0.1:{chosen_port}/")

    from .server import create_app  # 延迟导入：先让用户选完目录再拉起重依赖

    import uvicorn

    config = uvicorn.Config(
        create_app(),
        host="127.0.0.1",
        port=chosen_port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    if open_browser:
        threading.Thread(
            target=_open_when_ready,
            args=(chosen_port,),
            daemon=True,
        ).start()
        threading.Thread(
            target=_monitor_frontend,
            args=(server, chosen_port),
            daemon=True,
        ).start()

    try:
        server.run()
    except KeyboardInterrupt:
        _say("\n已停止。")
    return 0


def _open_when_ready(port: int) -> None:
    if _wait_for_api(port, STARTUP_TIMEOUT):
        webbrowser.open(f"http://127.0.0.1:{port}/")


def main() -> int:
    interactive = not (os.environ.get("COMFY_FETCH_HEADLESS") == "1")
    settings = Settings.load(use_config=True)
    comfy_root = resolve_comfy_root(settings, interactive=interactive)
    if comfy_root is None:
        if interactive:
            _say("未选择 ComfyUI 目录，已退出。")
        else:
            _say("未配置 ComfyUI 目录。设置 COMFY_ROOT 后重试。")
        return 1
    return launch(comfy_root, open_browser=interactive)


if __name__ == "__main__":
    raise SystemExit(main())
