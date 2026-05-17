"""AST lint: print() calls with status-prefix first arg must go to stderr.

Rule (W8-W3, treats H7 + W7-P9 class of bugs):
  If a print() call's first positional arg is a string literal starting
  with any of:
    [FAIL] [WARN] [OK] [ERROR] [INFO] [DEBUG] [SKIP] "$ "
  AND the call has no `file=` kwarg (defaulting to stdout)
  THEN report an error.

  Exception: paths under tests/ are skipped — tests may print to
  stdout for diagnostic readability.

Usage:
  python3 scripts/diagnostics/lint_stderr_routing.py [path...]
  Exits 0 if clean, 1 if violations found.
"""
import ast
import sys
from pathlib import Path

STATUS_PREFIXES = (
    "[FAIL]",
    "[WARN]",
    "[OK]",
    "[ERROR]",
    "[INFO]",
    "[DEBUG]",
    "[SKIP]",
    "$ ",
)


class StderrLintVisitor(ast.NodeVisitor):
    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.violations: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "print"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            text = node.args[0].value
            if any(text.startswith(p) for p in STATUS_PREFIXES):
                has_stderr = any(
                    kw.arg == "file"
                    and isinstance(kw.value, ast.Attribute)
                    and kw.value.attr == "stderr"
                    for kw in node.keywords
                )
                if not has_stderr:
                    self.violations.append((node.lineno, text[:40]))
        self.generic_visit(node)


def lint_file(path: Path) -> list[tuple[int, str]]:
    if path.suffix != ".py":
        return []
    try:
        source = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    v = StderrLintVisitor(str(path))
    v.visit(tree)
    return v.violations


def main() -> int:
    paths = [Path(p) for p in (sys.argv[1:] or ["scripts/"])]
    all_violations: list[tuple[str, int, str]] = []
    for p in paths:
        if p.is_file():
            files = [p]
        else:
            files = p.rglob("*.py")
        for f in files:
            # Skip tests/ regardless of how it appears in the path.
            parts = f.parts
            if "tests" in parts:
                continue
            for ln, snippet in lint_file(f):
                all_violations.append((str(f), ln, snippet))
    if all_violations:
        print(
            f"{len(all_violations)} stderr-routing violations:",
            file=sys.stderr,
        )
        for f, ln, s in all_violations:
            print(
                f"  {f}:{ln} - print({s!r}) should use file=sys.stderr",
                file=sys.stderr,
            )
        return 1
    print("stderr-routing lint clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
