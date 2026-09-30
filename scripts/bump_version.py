#!/usr/bin/env python3
"""Bump the semver version + maintain CHANGELOG.md, governed by Conventional Commits.

版本号单一真源：pyproject.toml。本脚本读 git log（自上次 tag 起）识别
conventional commit prefix，按以下规则决定 bump 等级：

* ``feat:``         → minor
* ``feat!:`` / body 含 ``BREAKING CHANGE:`` → major
* ``fix:``          → patch
* ``chore:`` / ``docs:`` / ``test:`` / ``build:`` / ``ci:`` /
  ``style:`` / ``refactor:`` / ``perf:``  → 不 bump（默认 patch 可手动覆盖）

执行步骤：
1. 自 ``git log <last_tag>..HEAD`` 解析 conventional prefix
2. 决定 bump 等级（自动或 CLI `--major`/`--minor`/`--patch` 覆盖）
3. 同步 X.Y.Z 到 6 处：pyproject / __init__ / spec / app.js / modelscope_client / config
4. 在 ``CHANGELOG.md``（Keep a Changelog 1.1.0）顶部新增本次版本段
5. 若指定 ``--no-changelog``，跳过 CHANGELOG 写入（兼容纯版本号 bump）

Usage::

    python scripts/bump_version.py               # 自动检测
    python scripts/bump_version.py --patch      # 强制 patch
    python scripts/bump_version.py --minor      # 强制 minor
    python scripts/bump_version.py --major      # 强制 major
    python scripts/bump_version.py --dry-run    # 只打印，不写文件
    make bump
"""
from __future__ import annotations

import argparse
import datetime
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PYPROJECT = ROOT / "pyproject.toml"
INIT = ROOT / "comfy_model_downloader" / "__init__.py"
SPEC = ROOT / "packaging" / "comfy-model-downloader.spec"
WEB_JS = ROOT / "comfy_model_downloader" / "web" / "app.js"
CHANGELOG = ROOT / "CHANGELOG.md"
USER_AGENT_FILES = (
    ROOT / "comfy_model_downloader" / "modelscope_client.py",
    ROOT / "comfy_model_downloader" / "config.py",
)

PYPROJECT_RE = re.compile(
    r'^(?P<indent>\s*)version\s*=\s*"(?P<v>\d+\.\d+\.\d+)"\s*$',
    re.MULTILINE,
)
INIT_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<prefix>__version__\s*=\s*)\"[^\"]+\"\s*$",
    re.MULTILINE,
)
SPEC_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<prefix>VERSION\s*=\s*)\"[^\"]+\"\s*$",
    re.MULTILINE,
)
WEB_RE = re.compile(
    r"(?P<indent>^[ \t]*)(?P<prefix>version:\s*')(?P<v>[^']+)(')",
    re.MULTILINE,
)
USER_AGENT_RE = re.compile(
    r"(?P<product>comfy-ui-model-downloader/)(?P<v>\d+\.\d+(?:\.\d+)?)"
)

CONVENTIONAL_RE = re.compile(
    r"^(?P<type>[a-zA-Z]+)(?P<bang>!)?(?:\((?P<scope>[^)]+)\))?:\s*(?P<subject>.+)$"
)

TYPE_TO_KEEP_A_CHANGELOG = {
    "feat": "Added",
    "fix": "Fixed",
    "refactor": "Changed",
    "perf": "Changed",
    "build": "Changed",
    "revert": "Reverted",
    "docs": None,
    "style": None,
    "test": None,
    "chore": None,
    "ci": None,
}

BUMP_FOR_TYPE = {"feat": "minor", "fix": "patch"}

BUMP_RANK = {"none": 0, "patch": 1, "minor": 2, "major": 3}


@dataclass
class BumpPlan:
    """一次 bump 的最终计划。"""

    old: str
    new: str
    kind: str
    entries: list[tuple[str, str]]  # (section, line)


def read_current_version() -> tuple[int, int, int]:
    text = PYPROJECT.read_text(encoding="utf-8")
    m = PYPROJECT_RE.search(text)
    if not m:
        raise RuntimeError(
            f"无法从 {PYPROJECT} 解析版本号（期望 `version = \"X.Y.Z\"`）"
        )
    major, minor, patch = m.group("v").split(".")
    return int(major), int(minor), int(patch)


def apply_version(new: str) -> int:
    """同步版本号到 6 处，返回实际改动文件数（含 CHANGELOG 由调用方处理）。"""
    edits = [
        (PYPROJECT, PYPROJECT_RE, rf'\g<indent>version = "{new}"',
         "pyproject.toml version"),
        (INIT, INIT_RE, rf'\g<indent>\g<prefix>"{new}"',
         "__init__.py __version__ fallback"),
        (SPEC, SPEC_RE, rf'\g<indent>\g<prefix>"{new}"',
         "spec VERSION (CFBundleShortVersionString)"),
        (WEB_JS, WEB_RE, rf"\g<indent>\g<prefix>{new}\g<4>",
         "web/app.js MOCK_CONFIG.version"),
    ]
    for path, pattern, repl, label in edits:
        optional = (path == SPEC)
        replace_once(path, pattern, repl, label, optional=optional)
    for path in USER_AGENT_FILES:
        replace_user_agent(path, new)
    return len(edits) + len(USER_AGENT_FILES)


def replace_once(path: Path, pattern: re.Pattern[str], repl, label: str, *, optional: bool = False) -> None:
    text = path.read_text(encoding="utf-8")
    new_text, count = pattern.subn(repl, text, count=1)
    if count == 0:
        if optional:
            print(f"  (skip) {label}: pattern not found (已动态化？)")
            return
        raise RuntimeError(
            f"{label} in {path} 期望恰好 1 处，实际 0 处。Pattern: {pattern.pattern!r}"
        )
    if count != 1:
        raise RuntimeError(f"{label} in {path} 期望恰好 1 处，实际 {count} 处")
    path.write_text(new_text, encoding="utf-8")


def replace_user_agent(path: Path, new_version: str) -> int:
    text = path.read_text(encoding="utf-8")
    new_text, count = USER_AGENT_RE.subn(
        lambda m: f"{m.group('product')}{new_version}", text
    )
    if count == 0:
        raise RuntimeError(f"{path} 找不到 User-Agent 版本字面量")
    path.write_text(new_text, encoding="utf-8")
    return count


def git_last_tag() -> str | None:
    """最近一个 release tag（含 v 前缀的 semver）。无 tag 时返回 None。"""
    res = subprocess.run(
        ["git", "tag", "--sort=-v:refname", "--merged"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if res.returncode != 0:
        return None
    for line in res.stdout.splitlines():
        line = line.strip()
        if re.match(r"^v?\d+\.\d+\.\d+$", line):
            return line
    return None


def git_log_subjects(since: str | None) -> list[str]:
    """读取 since tag 之后的 commit subject（不含 merge commit）。"""
    args = ["git", "log", "--pretty=format:%s", "--no-merges"]
    if since:
        args.append(f"{since}..HEAD")
    res = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        return []
    return [line for line in res.stdout.splitlines() if line]


def git_log_full(since: str | None) -> list[str]:
    """完整 commit message（subject + body），每条两行 #1 = subject #2 = blank 分割。"""
    args = ["git", "log", "--pretty=format:%s%n%b%n--END--", "--no-merges"]
    if since:
        args.append(f"{since}..HEAD")
    res = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        return []
    return [chunk.strip() for chunk in res.stdout.split("--END--") if chunk.strip()]


def detect_bump_kind(subjects: list[str], full_msgs: list[str]) -> str:
    """根据 conventional commits 推断 bump 等级（默认 patch）。"""
    rank = BUMP_RANK["patch"]
    for msg in full_msgs:
        first = msg.splitlines()[0] if msg else ""
        m = CONVENTIONAL_RE.match(first)
        if not m:
            continue
        if m.group("bang") == "!" or "BREAKING CHANGE" in msg.upper():
            return "major"
    for subj in subjects:
        m = CONVENTIONAL_RE.match(subj)
        if not m:
            continue
        if m.group("bang") == "!":
            return "major"
        t = m.group("type").lower()
        if t == "feat":
            return "minor"
        if t == "fix":
            rank = max(rank, BUMP_RANK["patch"])
    return "major" if rank >= BUMP_RANK["major"] else ("minor" if rank >= BUMP_RANK["minor"] else "patch")


def parse_changelog_entries(subjects: list[str]) -> list[tuple[str, str]]:
    """把 conventional commit subjects 归类到 Keep a Changelog 段。"""
    entries: dict[str, list[str]] = {}
    for subj in subjects:
        m = CONVENTIONAL_RE.match(subj)
        if not m:
            entries.setdefault("Changed", []).append(subj)
            continue
        t = m.group("type").lower()
        if t == "feat" and m.group("bang") == "!":
            entries.setdefault("Removed", []).append(subj[5:].strip())
            continue
        section = TYPE_TO_KEEP_A_CHANGELOG.get(t, "Changed" if t in TYPE_TO_KEEP_A_CHANGELOG else None)
        if section is None:
            continue
        scope = m.group("scope")
        scope_part = f"**{scope}:** " if scope else ""
        line = subj.split(":", 1)[1].strip() if ":" in subj else subj
        entries.setdefault(section, []).append(f"- {scope_part}{line}")
    return [(sec, "\n".join(lines)) for sec, lines in entries.items()]


CHANGELOG_HEADER = """# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

"""


def update_changelog(plan: BumpPlan) -> None:
    """在 CHANGELOG.md 顶部（[Unreleased] 后）插入新版本段。"""
    today = datetime.date.today().isoformat()
    lines = [f"## [{plan.new}] — {today}", ""]
    if plan.kind == "major":
        lines.append("### ⚠️ BREAKING CHANGES")
        lines.append("")
    for section, body in plan.entries:
        lines.append(f"### {section}")
        lines.append("")
        lines.append(body)
        lines.append("")
    new_block = "\n".join(lines)
    if not CHANGELOG.exists():
        CHANGELOG.write_text(CHANGELOG_HEADER + new_block, encoding="utf-8")
        return
    text = CHANGELOG.read_text(encoding="utf-8")
    if "## [Unreleased]" in text:
        text = text.replace("## [Unreleased]\n", f"## [Unreleased]\n\n{new_block}", 1)
    else:
        text = CHANGELOG_HEADER + new_block + "\n" + text[len(CHANGELOG_HEADER):]
    CHANGELOG.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--major", action="store_true", help="强制 major bump")
    parser.add_argument("--minor", action="store_true", help="强制 minor bump")
    parser.add_argument("--patch", action="store_true", help="强制 patch bump")
    parser.add_argument("--no-changelog", action="store_true", help="不更新 CHANGELOG.md")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写文件")
    args = parser.parse_args()

    flags = sum(bool(x) for x in (args.major, args.minor, args.patch))
    if flags > 1:
        parser.error("只能指定一个 --major/--minor/--patch")

    major, minor, patch = read_current_version()
    old_version = f"{major}.{minor}.{patch}"

    last_tag = git_last_tag()
    subjects = git_log_subjects(last_tag)
    full_msgs = git_log_full(last_tag)

    auto_kind = detect_bump_kind(subjects, full_msgs)
    if args.major:
        kind = "major"
    elif args.minor:
        kind = "minor"
    elif args.patch:
        kind = "patch"
    else:
        kind = auto_kind

    if kind == "major":
        new_version = f"{major + 1}.0.0"
    elif kind == "minor":
        new_version = f"{major}.{minor + 1}.0"
    else:
        new_version = f"{major}.{minor}.{patch + 1}"

    entries = parse_changelog_entries(subjects)
    plan = BumpPlan(old=old_version, new=new_version, kind=kind, entries=entries)

    print(f"Bumping {old_version} → {new_version} ({kind})")
    if last_tag:
        print(f"  since tag: {last_tag}, {len(subjects)} commits")
    else:
        print(f"  no prior tag, {len(subjects)} commits in repo")
    if subjects:
        print("  commit subjects:")
        for s in subjects:
            print(f"    - {s}")

    if args.dry_run:
        print("  (dry-run: 未写文件)")
        return 0

    apply_version(new_version)
    if not args.no_changelog:
        update_changelog(plan)
        print(f"  - {CHANGELOG.relative_to(ROOT)}")
    print(f"  - {PYPROJECT.relative_to(ROOT)}")
    print(f"  - {INIT.relative_to(ROOT)}")
    print(f"  - {SPEC.relative_to(ROOT)}")
    print(f"  - {WEB_JS.relative_to(ROOT)}")
    for p in USER_AGENT_FILES:
        print(f"  - {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())