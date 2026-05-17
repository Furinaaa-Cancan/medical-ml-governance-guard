#!/usr/bin/env bash
# MLGG dev environment setup. Idempotent. Activates local hooks.
#
# Usage:
#   ./scripts/setup-dev.sh                    # default: install hooks in current checkout
#   ./scripts/setup-dev.sh setup-worktree <branch>
#                                             # create ../<repo>-<branch> worktree
#                                             # sharing primary .venv/ via symlink
#
# See docs/adr/0004_worktrees_default.md §6-§7 for the shared-env rationale.

set -e

# ------------------------------------------------------------------------------
# Subcommand: setup-worktree <branch>
# ------------------------------------------------------------------------------
#
# Creates a sibling worktree directory at ../<repo>-<branch>, checks out (or
# creates) <branch>, symlinks .venv/ to the primary checkout's .venv/, and
# re-installs pre-commit so this worktree's .git/hooks/ is wired.
#
# Does NOT activate the env. Does NOT auto-cd. Caller does both.

setup_worktree() {
    local branch="$1"
    if [[ -z "$branch" ]]; then
        echo "ERROR: setup-worktree requires a branch name." >&2
        echo "Usage: $0 setup-worktree <branch>" >&2
        return 2
    fi

    # Primary checkout = the main worktree (where .git/ is a real directory,
    # not a .git file pointing into another worktree's .git/worktrees/).
    local primary
    primary="$(git rev-parse --path-format=absolute --git-common-dir)"
    primary="$(dirname "$primary")"   # strip /.git suffix → primary working tree

    local repo_name
    repo_name="$(basename "$primary")"

    local target_dir="${primary}/../${repo_name}-${branch}"

    if [[ -e "$target_dir" ]]; then
        echo "ERROR: $target_dir already exists. Refusing to overwrite." >&2
        return 2
    fi

    if [[ ! -d "${primary}/.venv" ]]; then
        echo "ERROR: primary .venv/ not found at ${primary}/.venv" >&2
        echo "Create it first:" >&2
        echo "  cd ${primary} && python -m venv .venv && source .venv/bin/activate && pip install -e \".[dev]\"" >&2
        return 2
    fi

    echo "==> creating worktree at ${target_dir} on branch ${branch}"
    git -C "$primary" worktree add -B "$branch" "$target_dir" main

    echo "==> symlinking .venv/ to share primary env"
    # Resolve absolute path of primary .venv/ so the symlink doesn't break
    # if the user later moves the sibling worktree directory.
    local primary_venv_abs
    primary_venv_abs="$(cd "${primary}/.venv" && pwd)"
    ln -s "$primary_venv_abs" "${target_dir}/.venv"
    echo "  ✅ ${target_dir}/.venv -> ${primary_venv_abs}"

    echo "==> installing per-worktree pre-commit hook"
    (
        cd "$target_dir"
        if command -v pre-commit &>/dev/null; then
            pre-commit install
            echo "  ✅ pre-commit installed in worktree"
        else
            echo "  ⚠️  pre-commit not in PATH yet. Activate .venv first, then re-run from worktree."
        fi
    )

    echo ""
    echo "Worktree ready. Next:"
    echo "  cd ${target_dir}"
    echo "  source .venv/bin/activate"
    echo "  pytest -q   # confirm shared env works"
}

# ------------------------------------------------------------------------------
# Worktree health check
# ------------------------------------------------------------------------------
#
# If we're being run from a linked worktree (not the primary), warn when
# .venv/ is a real directory rather than a symlink — that means the user
# silently de-shared the env and is paying the per-worktree disk cost.

check_worktree_env_share() {
    # .git is a file (not a dir) in a linked worktree
    if [[ -f .git ]]; then
        if [[ -d .venv && ! -L .venv ]]; then
            echo ""
            echo "  ⚠️  WORKTREE WARNING: .venv/ here is a real directory, not a symlink."
            echo "      Per ADR 0004 §6 the recommended pattern is to symlink the"
            echo "      primary checkout's .venv/ so all worktrees share one env."
            echo "      To fix:"
            echo "        rm -rf .venv"
            echo "        ln -s /abs/path/to/primary/ml-leakage-guard/.venv .venv"
            echo ""
        elif [[ -L .venv ]]; then
            local target
            target="$(readlink .venv)"
            echo "  ✅ worktree .venv/ -> ${target} (shared per ADR 0004 §6)"
        else
            echo "  ℹ️  worktree has no .venv/ yet — create symlink to primary per ADR 0004 §7."
        fi
    fi
}

# ------------------------------------------------------------------------------
# Subcommand dispatch
# ------------------------------------------------------------------------------

if [[ "${1:-}" == "setup-worktree" ]]; then
    setup_worktree "${2:-}"
    exit $?
fi

# ------------------------------------------------------------------------------
# Default: install hooks in current checkout
# ------------------------------------------------------------------------------

cd "$(git rev-parse --show-toplevel)"

echo "==> setting up MLGG local hooks"

# pre-commit
if command -v pre-commit &>/dev/null; then
    pre-commit install
    echo "  ✅ pre-commit installed"
else
    echo "  ⚠️  pre-commit not installed. Run: pip install pre-commit"
fi

# git hooks dir
git config core.hooksPath .githooks
echo "  ✅ git hooks dir set to .githooks"

# sanity
if python3 -c "import sentence_transformers" 2>/dev/null; then
    echo "  ✅ sentence_transformers available (RAG smoke OK)"
else
    echo "  ⚠️  sentence_transformers missing. RAG smoke will skip."
fi

check_worktree_env_share

echo ""
echo "Local hook activation complete."
echo "Try: git commit --allow-empty -m 'hooks test'"

# === Optional: parallel-session worktree ===
echo ""
echo "Tip: for parallel sessions, use:"
echo "  ./scripts/setup-dev.sh setup-worktree session-N"
echo "See docs/adr/0004_worktrees_default.md §6-§7 for shared-.venv/ rationale."
