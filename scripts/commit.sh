#!/usr/bin/env bash
# Conventional Commits 提交包装器：自动 bump + 记录 changelog。
#
# Usage:
#   scripts/commit.sh "feat(server): add /api/cancel endpoint"
#   scripts/commit.sh "fix(downloader): prevent zombie tasks"
#   scripts/commit.sh "feat!: remove legacy auth"   # BREAKING → major bump
#   scripts/commit.sh --no-bump "docs: typo"        # docs/chore/test → 不 bump
#   scripts/commit.sh --amend                       # 复用上一次 commit msg
#
# 自动行为：
#   * 校验 commit msg 匹配 Conventional Commits 1.0
#   * feat/feat! → bump minor (含 BREAKING 升级 major)
#   * fix       → bump patch
#   * chore/docs/test/build/ci/style/refactor/perf → 默认不 bump
#     （可用 --force-bump 或 --major/--minor/--patch 强制）
#   * bump_version.py 自动更新 6 处版本号 + 写 CHANGELOG.md
#   * 最终 commit 包含代码改动 + 版本/changelog 改动

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BUMP_KIND=""
NO_BUMP=0
AMEND=0
while [ $# -gt 0 ]; do
    case "$1" in
        --major|--minor|--patch) BUMP_KIND="${1#--}"; shift ;;
        --no-bump)                NO_BUMP=1; shift ;;
        --amend)                  AMEND=1; shift ;;
        -h|--help)
            sed -n '2,21p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
            exit 0 ;;
        --*) echo "未知选项: $1" >&2; exit 1 ;;
        *) break ;;
    esac
done

# 取 commit msg（--amend 时复用上一次）
if [ "$AMEND" -eq 1 ]; then
    if ! COMMIT_MSG="$(git log -1 --pretty=%B)"; then
        echo "git log 失败" >&2; exit 1
    fi
    echo "复用上一次 commit msg:"
else
    if [ $# -lt 1 ]; then
        echo "用法: $0 [--major|--minor|--patch|--no-bump] <conventional-commit-msg>" >&2
        echo "   或: $0 --amend" >&2
        exit 1
    fi
    COMMIT_MSG="$*"
fi
echo "$COMMIT_MSG"
echo

# Conventional Commits 校验
TYPE_RE='^(feat|fix|chore|docs|style|refactor|perf|test|build|ci|revert)(!)?(\([^)]+\))?: .+$'
if ! [[ "$COMMIT_MSG" =~ $TYPE_RE ]]; then
    echo "✗ commit msg 不符合 Conventional Commits 格式" >&2
    echo "  期望形如: type(scope): subject" >&2
    echo "  示例: feat(server): add /api/cancel endpoint" >&2
    echo "  type ∈ {feat,fix,chore,docs,style,refactor,perf,test,build,ci,revert}" >&2
    exit 1
fi

TYPE="${BASH_REMATCH[1]}"
BANG="${BASH_REMATCH[2]}"

# 决定 bump
if [ "$NO_BUMP" -eq 1 ]; then
    BUMP_KIND=""
elif [ -z "$BUMP_KIND" ]; then
    case "$TYPE" in
        feat)  BUMP_KIND="minor" ;;
        fix)   BUMP_KIND="patch" ;;
        chore|docs|style|refactor|perf|test|build|ci|revert)
            BUMP_KIND="" ;;  # 不 bump
    esac
fi

if [ -n "$BANG" ]; then
    BUMP_KIND="major"
    echo "⚠ BREAKING CHANGE 标记 → major bump"
fi

# 执行 bump
if [ -n "$BUMP_KIND" ]; then
    echo "→ 准备 $BUMP_KIND bump..."
    if ! /opt/anaconda3/envs/comfy-fetch/bin/python scripts/bump_version.py "--$BUMP_KIND"; then
        echo "✗ bump_version.py 失败" >&2
        exit 1
    fi
    echo
fi

# 校验：未追踪的代码改动 + (bump 产生的新文件)
if [ -z "$(git status --porcelain)" ]; then
    echo "✗ 没有待提交改动" >&2
    exit 1
fi

git add -A

# 提交（--amend 时附加）
if [ "$AMEND" -eq 1 ]; then
    git commit --amend --no-edit
else
    git commit -m "$COMMIT_MSG"
fi

echo
echo "✓ 提交完成：$(git log -1 --pretty=%h) $(git log -1 --pretty=%s)"