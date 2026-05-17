#!/usr/bin/env bash
# MLGG dev environment setup. Idempotent. Activates local hooks.

set -e
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

echo ""
echo "Local hook activation complete."
echo "Try: git commit --allow-empty -m 'hooks test'"

# === Optional: parallel-session worktree ===
echo ""
echo "Tip: for parallel sessions, use: git worktree add ../$(basename "$PWD")-session-N main"
echo "See docs/adr/0004_worktrees_default.md for rationale."
