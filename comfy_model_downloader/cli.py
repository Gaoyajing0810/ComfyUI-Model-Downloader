"""ComfyUI Model Downloader 命令行入口。"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import unicodedata
from pathlib import Path
from typing import Any

import click

from .config import Settings
from .mapping import CATEGORY_DIRS
from .parser import WorkflowParseError, load_workflow
from .plan import Plan, build_plan
from .resolver import CuratedTable, Resolver
from .scan import ComfyRoot, LocalIndex
from .verify import BAD_STATUSES, VerifyStatus, verify_file

BANNER = "ComfyUI Model Downloader · 从魔搭补齐 ComfyUI 模型"


def _fail(msg: str) -> None:
    raise click.ClickException(msg)


def _resolve_root(settings: Settings, comfy_root: str | None, models_dir: str | None) -> ComfyRoot:
    if comfy_root:
        settings.comfy_root = Path(comfy_root).expanduser()
    if models_dir:
        settings.models_dir = Path(models_dir).expanduser()
    if settings.models_dir is None and settings.comfy_root is not None:
        settings.models_dir = settings.comfy_root / "models"
    if settings.models_dir is None:
        _fail("未指定 ComfyUI 根目录。请用 --comfy-root 指定，或设置环境变量 COMFY_ROOT。")
    if not Path(settings.models_dir).is_dir():
        _fail(f"模型目录不存在：{settings.models_dir}。请确认 ComfyUI 的 models 目录位置。")
    return ComfyRoot.resolve(settings.comfy_root, settings.models_dir)


def _make_resolver(settings: Settings, resolve: bool) -> Resolver | None:
    if not resolve:
        return None
    from .modelscope_client import ModelScopeIndex

    index = ModelScopeIndex(token=settings.token, timeout=settings.timeout)
    curated = CuratedTable.load(settings.curated_path)
    resolver = Resolver(index, curated)

    def _resolve(category: str, filename: str, ref: Any) -> Any:
        return resolver.resolve(category, filename)

    return _resolve


def _build_plan(
    settings: Settings, workflow: str, comfy_root: str | None, models_dir: str | None,
    resolve: bool = True,
) -> tuple[ComfyRoot, LocalIndex, Plan]:
    root = _resolve_root(settings, comfy_root, models_dir)
    try:
        parsed = load_workflow(workflow)
    except WorkflowParseError as exc:
        _fail(str(exc))

    index = LocalIndex.build(root, list(CATEGORY_DIRS), settings.health_check_existing)
    resolver = _make_resolver(settings, resolve)
    plan = build_plan(
        job_id="cli",
        workflow_name=Path(workflow).name if Path(workflow).suffix == ".json" else "workflow",
        parse_result=parsed,
        local_index=index,
        resolver=resolver,
        models_dir=str(root.models_dir),
        comfy_root=str(root.root) if root.root else "",
        allow_basename_match=settings.allow_basename_match,
    )
    return root, index, plan


def _fmt_size(n: int | None) -> str:
    if not n:
        return "-"
    v = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024 or unit == "TB":
            return f"{v:.2f} {unit}" if unit != "B" else f"{int(v)} B"
        v /= 1024
    return f"{v:.2f} TB"


_STATUS_LABEL = {"exact": "已存在", "basename": "其他目录", "missing": "缺失", "corrupt": "损坏"}
_STATUS_COLOR = {"exact": "green", "basename": "yellow", "missing": "white", "corrupt": "red"}


def _pad(text: str, width: int) -> str:
    """按终端显示宽度补齐（全角字符占 2 列）。"""
    shown = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    if shown <= width:
        return text + " " * (width - shown)
    return text[: max(1, width - 1)] + "…"


def _row(cells: list[tuple[str, int]], color: str = "white") -> None:
    click.secho("  ".join(_pad(c, w) for c, w in cells).rstrip(), fg=color)


def _print_plan(plan: Plan) -> None:
    t = plan.totals()
    click.secho(f"\n工作流：{plan.workflow_name}", fg="cyan", bold=True)
    click.echo(
        f"节点 {plan.parse.node_count} 个 · 引用模型 {t['total']} 个 · "
        f"已存在 {t['present']} · 待下载 {t['to_download']} · "
        f"待人工确认 {t['unresolved']} · 需下载 {_fmt_size(t['bytes_to_download'])}\n"
    )
    _row([("#", 3), ("目标子目录", 17), ("文件名", 44), ("本地", 10),
          ("魔搭仓库", 30), ("置信", 6), ("大小", 12)], "white")
    click.secho("\u2500" * 128, fg="black")
    for i in plan.items:
        st = _STATUS_LABEL[i.local.status]
        sk = i.source
        subdir = i.target_rel.split("/", 1)[0]
        if sk.kind.value == "none":
            _row([(str(i.item_id), 3), (subdir, 17), (i.ref.filename, 44), (st, 10),
                  ("未找到可信来源", 30), ("\u2014", 6), (_fmt_size(sk.size), 12)], "magenta")
            for c in sk.candidates[:3]:
                click.secho(f"      候选 {c.repo_id} :: {c.file_path}  ({c.score:.2f})", fg="black")
        else:
            _row([(str(i.item_id), 3), (subdir, 17), (i.ref.filename, 44), (st, 10),
                  (sk.repo_id, 30), (sk.confidence.value, 6), (_fmt_size(sk.size), 12)],
                 _STATUS_COLOR[i.local.status])
            if st == "其他目录" and i.local.note:
                click.secho(f"      \u21b3 {i.local.note}", fg="black")


def _print_local(plan: Plan) -> None:
    click.secho(f"\n工作流：{plan.workflow_name}", fg="cyan", bold=True)
    click.echo(f"节点 {plan.parse.node_count} 个 · 引用模型 {len(plan)} 个\n")
    _row([("#", 3), ("落盘位置", 46), ("本地状态", 10)], "white")
    click.secho("\u2500" * 62, fg="black")
    for i in plan.items:
        _row([(str(i.item_id), 3), (i.target_rel, 46), (_STATUS_LABEL[i.local.status], 10)],
             _STATUS_COLOR[i.local.status])
        if i.local.note:
            click.secho(f"      \u21b3 {i.local.note}", fg="black")
    t = plan.totals()
    click.echo(
        f"\n小结：已存在 {t['present']} · 缺失 {t['missing']}"
        f"（其中损坏 {t['corrupt']}）· 未定类 {t['no_category']}\n"
    )


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="comfy-ui-model-downloader", prog_name="comfy-ui-model-downloader")
def main() -> None:
    """解析 ComfyUI 工作流所需模型，并从 ModelScope 魔搭社区下载到本地模型目录。"""
    click.secho(BANNER, fg="cyan", bold=True)


@main.command()
@click.argument("workflow", type=click.Path(exists=True, dir_okay=False))
@click.option("--comfy-root", type=click.Path(exists=True, file_okay=False), help="ComfyUI 根目录")
@click.option("--models-dir", type=click.Path(exists=True, file_okay=False), help="models 目录（默认 <comfy-root>/models）")
@click.option("--json", "as_json", is_flag=True, help="以 JSON 输出")
def scan(workflow: str, comfy_root: str | None, models_dir: str | None, as_json: bool) -> None:
    """仅解析工作流并对照本地模型，不联网、不下载。"""
    settings = Settings.load()
    _, _, plan = _build_plan(settings, workflow, comfy_root, models_dir, resolve=False)
    if as_json:
        click.secho(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_local(plan)


@main.command()
@click.argument("workflow", type=click.Path(exists=True, dir_okay=False))
@click.option("--comfy-root", type=click.Path(exists=True, file_okay=False), help="ComfyUI 根目录")
@click.option("--models-dir", type=click.Path(exists=True, file_okay=False), help="models 目录")
@click.option("--offline", is_flag=True, help="跳过魔搭来源匹配")
@click.option("--json", "as_json", is_flag=True, help="以 JSON 输出")
def plan_cmd(workflow: str, comfy_root: str | None, models_dir: str | None, offline: bool, as_json: bool) -> None:
    """解析工作流并匹配魔搭来源，输出下载计划（不下载）。"""
    settings = Settings.load()
    _, _, plan = _build_plan(settings, workflow, comfy_root, models_dir, resolve=not offline)
    if as_json:
        click.echo(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_plan(plan)


@main.command()
@click.argument("workflow", type=click.Path(exists=True, dir_okay=False))
@click.option("--comfy-root", type=click.Path(exists=True, file_okay=False), help="ComfyUI 根目录")
@click.option("--models-dir", type=click.Path(exists=True, file_okay=False), help="models 目录")
@click.option("--concurrency", type=int, help="并发下载数")
@click.option("--dry-run", is_flag=True, help="只打印将要下载的条目")
@click.option("--json", "as_json", is_flag=True, help="以 JSON 输出最终结果")
def fetch(workflow: str, comfy_root: str | None, models_dir: str | None,
          concurrency: int | None, dry_run: bool, as_json: bool) -> None:
    """执行下载：解析 → 匹配 → 下载 → 校验。"""
    from .downloader import DownloadManager
    from .modelscope_client import ModelScopeFetcher

    settings = Settings.load()
    if concurrency:
        settings.concurrency = concurrency
    root, _, plan = _build_plan(settings, workflow, comfy_root, models_dir)
    _print_plan(plan)

    todo = plan.downloadable
    if not todo:
        click.secho("\n没有需要下载的模型。", fg="green")
        return
    free = shutil.disk_usage(root.models_dir).free
    need = sum(i.source.size or 0 for i in todo)
    click.secho(f"待下载 {len(todo)} 个 · {_fmt_size(need)} · 磁盘剩余 {_fmt_size(free)}")
    if need and need > free:
        _fail(f"磁盘空间不足：需要 {_fmt_size(need)}，仅剩 {_fmt_size(free)}")
    if dry_run:
        click.secho("\n--dry-run：未实际下载。", fg="yellow")
        return

    manager = DownloadManager(settings)
    task = manager.create(plan, [i.item_id for i in todo])
    fetcher = ModelScopeFetcher(
        token=settings.token, retries=settings.retries, timeout=settings.timeout,
        deep_verify=settings.deep_verify,
    )
    try:
        asyncio.run(manager.run(task, plan, fetcher))
    except KeyboardInterrupt:
        task.cancel()
        click.secho("\n已取消。", fg="yellow")
        sys.exit(130)

    result = task.to_dict()
    if as_json:
        click.secho(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_task_result(result)
    sys.exit(0 if result["state"] == "done" else 1)


@main.command()
@click.option("--comfy-root", type=click.Path(exists=True, file_okay=False), help="ComfyUI 根目录")
@click.option("--models-dir", type=click.Path(exists=True, file_okay=False), help="models 目录")
@click.option("--category", "categories", multiple=True, help="只校验指定类别（可重复）")
@click.option("--json", "as_json", is_flag=True, help="以 JSON 输出")
def verify(comfy_root: str | None, models_dir: str | None,
           categories: tuple[str, ...], as_json: bool) -> None:
    """校验本地已有模型文件是否完整。"""
    from .scan import iter_model_files

    settings = Settings.load()
    root = _resolve_root(settings, comfy_root, models_dir)
    cats = list(categories) or list(CATEGORY_DIRS)
    rows: list[dict[str, Any]] = []
    for cat in cats:
        for f in iter_model_files(root, cat):
            r = verify_file(f, deep=settings.deep_verify)
            rows.append(r.to_dict())

    bad = [r for r in rows if r["status"] in {s.value for s in BAD_STATUSES}]
    if as_json:
        click.echo(json.dumps({"total": len(rows), "bad": len(bad), "items": rows},
                              ensure_ascii=False, indent=2))
    else:
        for r in bad:
            click.secho(f"[{r['status']}] {r['path']}", fg="red")
            click.secho(f"    {r['detail']}", fg="black")
        click.secho(f"\n共检查 {len(rows)} 个模型文件，问题 {len(bad)} 个。")
    sys.exit(1 if bad else 0)


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="监听地址")
@click.option("--port", default=8188, show_default=True, help="监听端口")
@click.option("--comfy-root", type=click.Path(exists=True, file_okay=False), help="ComfyUI 根目录")
@click.option("--models-dir", type=click.Path(exists=True, file_okay=False), help="models 目录")
@click.option("--reload", is_flag=True, help="开发模式，代码变更自动重载")
def serve(host: str, port: int, comfy_root: str | None, models_dir: str | None, reload: bool) -> None:
    """启动 Web 操作界面。"""
    import uvicorn

    if comfy_root:
        import os

        os.environ["COMFY_ROOT"] = str(Path(comfy_root).expanduser())
    if models_dir:
        import os

        os.environ["COMFY_MODELS_DIR"] = str(Path(models_dir).expanduser())
    click.secho(f"操作界面：http://{host}:{port}", fg="green", bold=True)
    uvicorn.run("comfy_model_downloader.server:app", host=host, port=port, reload=reload, log_level="info")


def _print_task_result(result: dict[str, Any]) -> None:
    ov = result["overall"]
    color = "green" if result["state"] == "done" else "red"
    click.secho(
        f"\n{result['state'].upper()} · 成功 {ov['done'] - ov['failed']}/{ov['total']}"
        f" · 失败 {ov['failed']} · 传输 {_fmt_size(ov['bytes'])}",
        fg=color, bold=True,
    )
    for it in result["items"]:
        if it["state"] in {"done", "failed", "skipped", "unresolved"}:
            c = {"done": "green", "skipped": "bright_black", "failed": "red", "unresolved": "magenta"}[it["state"]]
            click.secho(f"  [{it['state']:<10}] {it['filename']:<44} {it.get('dest') or it.get('error') or ''}", fg=c)
    click.echo(f"\n模型目录：{result['models_dir']}")


if __name__ == "__main__":
    main()
