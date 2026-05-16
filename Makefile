# MLGG developer convenience targets.
#
# Keep this thin: routing is the responsibility of scripts/orchestration/mlgg.py.
# Targets here only exist to make CI-parity local checks (and hook activation)
# discoverable to new contributors.

.PHONY: help pre-push install-hooks

help:
	@echo "MLGG make targets:"
	@echo "  make pre-push       Run the same checks as the pre-push hook (no push)."
	@echo "  make install-hooks  Activate .githooks/ so git uses our hooks."

# Run the same checks the pre-push hook runs, without actually pushing.
# Useful for testing the hook or running checks ad hoc.
pre-push:
	@bash .githooks/pre-push

# Activate the .githooks/ directory so git uses our hooks.
# One-time per clone. Bypass once: `git push --no-verify`.
install-hooks:
	@git config core.hooksPath .githooks
	@echo "[OK] git hooks activated (core.hooksPath = .githooks)"
	@echo "     pre-push will now run before every 'git push'."
	@echo "     Bypass once: git push --no-verify"
