"""PyInstaller 入口。

打包成 .app 后双击没有终端可看，崩溃必须以原生弹窗呈现，否则用户只看到闪退。
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def _log_path() -> Path:
    base = Path.home() / "Library" / "Logs" / "comfy-ui-model-downloader"
    return base / "launcher.log"


def _append_log(text: str) -> None:
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except OSError:
        pass


def _alert(title: str, message: str) -> None:
    if sys.platform != "darwin":
        return
    import subprocess

    def esc(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    subprocess.run(
        [
            "osascript",
            "-e",
            f'display alert "{esc(title)}" message "{esc(message)}" as critical',
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=60,
        check=False,
    )


def _real_main() -> int:
    from comfy_model_downloader.launcher import main

    return main()


def _ensure_streams() -> None:
    """窗口模式下 PyInstaller 把 sys.stdout/sys.stderr 置为 None。

    uvicorn 的 DefaultFormatter 会调 sys.stderr.isatty()，拿到 None 直接 AttributeError，
    而 logging 只会报一句泛化的 "Unable to configure formatter"，很难查。
    这里先给它们一个真实句柄（丢弃输出，日志由 _Tee 落盘）。
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8", buffering=1))


def _diag() -> int:
    """冻结环境下打印依赖导入的真实异常，打包问题只能靠这个查。"""
    import logging.config
    import traceback

    report: list[str] = []
    for name in (
        "uvicorn",
        "uvicorn.config",
        "uvicorn._ansi",
        "uvicorn.logging",
        "uvicorn._compat",
        "modelscope_hub",
        "httpx",
        "fastapi",
        "cryptography.hazmat.bindings._rust",
    ):
        try:
            __import__(name)
            report.append(f"OK   {name}")
        except BaseException:
            report.append(f"FAIL {name}\n{traceback.format_exc()}")

    try:
        import uvicorn.config as uc

        from logging.config import DictConfigurator

        DictConfigurator({}).configure_formatter(uc.LOGGING_CONFIG["formatters"]["default"])
        report.append("OK   uvicorn formatter 构造")
    except BaseException:
        report.append(f"FAIL uvicorn formatter 构造\n{traceback.format_exc()}")

    try:
        import logging.config

        import uvicorn.config as uc

        logging.config.dictConfig(uc.LOGGING_CONFIG)
        report.append("OK   uvicorn dictConfig")
    except BaseException:
        report.append(f"FAIL uvicorn dictConfig\n{traceback.format_exc()}")

    text = "\n".join(report)
    _append_log("---- 诊断 ----\n" + text)
    with open(os.devnull, "w", encoding="utf-8") as sink:
        real, sys.stdout = sys.stdout, sink
        print(text)
        sys.stdout = real
    return 0


def main() -> int:
    if "--diag" in sys.argv:
        _ensure_streams()
        return _diag()
    _append_log(f"=== 启动 {__import__('datetime').datetime.now():%Y-%m-%d %H:%M:%S} pid={os.getpid()}")
    _ensure_streams()
    stdout, stderr = sys.stdout, sys.stderr

    class _Tee:
        def write(self, text: str) -> int:
            _append_log(text.rstrip("\n"))
            return stdout.write(text)

        def flush(self) -> None:
            stdout.flush()

        def __getattr__(self, item: str):
            # logging 与 uvicorn 会摸 isatty/encoding/fileno，缺任何一个都会抛
            # AttributeError，logging 只会报一句泛化的 formatter 错误，极难排查
            return getattr(stdout, item)

    sys.stdout = _Tee()  # type: ignore[assignment]
    sys.stderr = _Tee()  # type: ignore[assignment]
    try:
        code = _real_main()
    except SystemExit as exc:
        code = int(exc.code or 0)
    except BaseException:
        detail = traceback.format_exc()
        _append_log(detail)
        _alert("ComfyUI Model Downloader 启动失败", f"{detail[-1400:]}\n\n日志：{_log_path()}")
        return 1
    finally:
        sys.stdout, sys.stderr = stdout, stderr
    _append_log(f"=== 退出 code={code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
