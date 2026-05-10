"""R029: Credentials embedded in code/data availability sections.

Detects patterns like ``username: alice password: s3cret``,
``ftp://user:pwd@host/path``, or ``https://user:pwd@host`` that occur in
Python string literals, docstrings, or auxiliary text files
(README.md, code_availability.txt, AVAILABILITY.txt, ...).

Originated from a real-world finding: a peer-reviewed paper distributed
its dataset via an institutional FTP whose code-availability paragraph
embedded the username and password directly in the manuscript text.
This is a hard governance issue — credentials in any published artefact
exposes the host, violates principle of least privilege, and makes
revocation impossible without breaking every downstream reproduction.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterable, List, Tuple

from mlgg_lint.models import Diagnostic, Location, Severity
from mlgg_lint.rules import register
from mlgg_lint.rules.base import BaseRule


# ── Credential patterns ──────────────────────────────────────────────────────
#
# Each pattern targets a different shape of leak:
#
#   * URL_CRED: `<scheme>://<user>:<pass>@<host>` — RFC-3986 embedded
#     userinfo. Catches FTP/SFTP/HTTP/HTTPS download URLs that paste
#     credentials inline (the most common form in availability
#     paragraphs).
#
#   * USER_PASS_PAIR: prose like "Username: alice Password: s3cret" or
#     "username=alice password=s3cret". Requires the two keywords to
#     co-occur within a short window so we don't flag unrelated
#     mentions.
#
#   * LOGIN_TOKEN: prose like "login: alice" / "login=alice" — weaker
#     signal, only emitted when accompanied by another credential cue
#     in the same string (see _scan_string).
#
# Patterns are intentionally conservative: we report only when a
# credential VALUE is present, never on bare keywords.
_URL_CRED = re.compile(
    r"\b(?:ftp|ftps|sftp|https?)://[^\s/@:]+:[^\s/@]+@[^\s)\]'\"]+",
    re.IGNORECASE,
)

_USER_PASS_PAIR = re.compile(
    r"\b(?:user(?:name)?)\s*[:=]\s*\S+[\s,;]+(?:pass(?:word|wd)?|pwd)\s*[:=]\s*\S+",
    re.IGNORECASE | re.DOTALL,
)

_LOGIN_TOKEN = re.compile(
    r"\blogin\s*[:=]\s*\S+",
    re.IGNORECASE,
)

# Patterns that, when present in the same string as a LOGIN_TOKEN, raise
# our confidence that this is a real credential paragraph rather than
# code that happens to mention "login".
_LOGIN_CONTEXT_CUES = re.compile(
    r"\b(?:password|pwd|pass|credential|host|server|ftp)\b",
    re.IGNORECASE,
)

# File names we treat as "code/data availability" auxiliary text.
# Matched case-insensitively against the basename.
_TEXT_FILE_PATTERNS = (
    re.compile(r"^readme(\.|$)", re.IGNORECASE),
    re.compile(r"^code[_-]?availability", re.IGNORECASE),
    re.compile(r"^data[_-]?availability", re.IGNORECASE),
    re.compile(r"^availability", re.IGNORECASE),
    re.compile(r"^supplement", re.IGNORECASE),
    re.compile(r"^supp(_|-)?info", re.IGNORECASE),
    re.compile(r"^methods", re.IGNORECASE),
)

_TEXT_SUFFIXES = {".md", ".rst", ".txt"}

# Skip very large auxiliary text files to keep scans bounded.
_MAX_TEXT_BYTES = 1 * 1024 * 1024  # 1 MiB


def _scan_string(text: str) -> List[Tuple[str, str]]:
    """Return a list of (pattern_label, matched_substring) hits in ``text``."""
    hits: List[Tuple[str, str]] = []

    for m in _URL_CRED.finditer(text):
        hits.append(("url-embedded-credentials", m.group(0)))

    for m in _USER_PASS_PAIR.finditer(text):
        hits.append(("user-password-pair", m.group(0)))

    # LOGIN_TOKEN is noisy on its own; only emit when corroborated.
    if _LOGIN_CONTEXT_CUES.search(text):
        for m in _LOGIN_TOKEN.finditer(text):
            hits.append(("login-with-credential-context", m.group(0)))

    return hits


def _redact(snippet: str, max_len: int = 80) -> str:
    """Truncate the matched snippet so we never echo a full credential
    back to the user verbatim. Keeps the leading scheme/keyword for
    diagnostics; replaces the rest with an ellipsis once we pass the
    `:` separator after the keyword.
    """
    snippet = snippet.strip()
    if len(snippet) > max_len:
        snippet = snippet[:max_len] + "..."
    return snippet


def is_availability_text_file(path: Path) -> bool:
    """Return True iff ``path`` looks like an availability/readme file."""
    if path.suffix.lower() not in _TEXT_SUFFIXES:
        return False
    name = path.name
    return any(p.match(name) for p in _TEXT_FILE_PATTERNS)


def scan_text_file(path: Path, display: str) -> List[Diagnostic]:
    """Scan a non-Python text file (README.md / code_availability.txt /
    similar) for credential patterns.

    Used by the engine to extend R029 coverage beyond Python AST
    string-literal scanning. Returns one diagnostic per hit.
    """
    diagnostics: List[Diagnostic] = []
    try:
        size = path.stat().st_size
    except OSError:
        return diagnostics
    if size > _MAX_TEXT_BYTES:
        return diagnostics
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return diagnostics

    # Build offset->line map so whole-file matches still get a line number.
    offsets = [0]
    for i, ch in enumerate(source):
        if ch == "\n":
            offsets.append(i + 1)

    def _line_of(offset: int) -> int:
        """Return 1-based line number for a character offset."""
        lo, hi = 0, len(offsets) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if offsets[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    for label, snippet, start in _scan_string_with_offsets(source):
        diagnostics.append(
            Diagnostic(
                rule_id=CredentialsInCodeAvailability.id,
                rule_name=CredentialsInCodeAvailability.name,
                severity=CredentialsInCodeAvailability.severity,
                message=(
                    f"Credential pattern ({label}) detected in availability "
                    f"text file: '{_redact(snippet)}'. Code/data availability "
                    f"sections must NOT contain credentials."
                ),
                location=Location(file=display, line=_line_of(start), col=0),
                remediation=CredentialsInCodeAvailability.remediation,
                details={"pattern": label},
            )
        )
    return diagnostics


def _scan_string_with_offsets(text: str) -> List[Tuple[str, str, int]]:
    """Like _scan_string but also returns each match's start offset."""
    hits: List[Tuple[str, str, int]] = []
    for m in _URL_CRED.finditer(text):
        hits.append(("url-embedded-credentials", m.group(0), m.start()))
    for m in _USER_PASS_PAIR.finditer(text):
        hits.append(("user-password-pair", m.group(0), m.start()))
    if _LOGIN_CONTEXT_CUES.search(text):
        for m in _LOGIN_TOKEN.finditer(text):
            hits.append(("login-with-credential-context", m.group(0), m.start()))
    return hits


@register
class CredentialsInCodeAvailability(BaseRule):
    id = "R029"
    name = "credentials-in-code-availability"
    severity = Severity.ERROR
    description = (
        "Credentials embedded in source string literals, docstrings, or "
        "auxiliary text files (README, code_availability). Includes "
        "username/password pairs and URLs with inline userinfo "
        "(ftp://user:pass@host)."
    )
    remediation = (
        "Code/data availability sections must NOT contain credentials. "
        "Use a private mirror with an explicit access-request protocol, "
        "or remove credentials and document a request workflow (DUA, "
        "controlled-access repository, contact email)."
    )
    tags = ("governance", "security", "credentials")

    def visit_Constant(self, node: ast.Constant) -> None:  # noqa: N802
        if isinstance(node.value, str):
            self._scan_node_string(node, node.value)
        self.generic_visit(node)

    def _scan_node_string(self, node: ast.AST, value: str) -> None:
        if not value or len(value) > 100_000:
            # Defensive: skip absurdly long literals (binary blobs, etc.)
            return
        for label, snippet in _scan_string(value):
            self.report(
                node,
                f"Credential pattern ({label}) detected in string literal: "
                f"'{_redact(snippet)}'. Code/data availability sections "
                f"must NOT contain credentials.",
                pattern=label,
            )


def iter_text_file_candidates(root: Path) -> Iterable[Path]:
    """Yield availability-style text files under ``root``.

    Used by the engine when it descends into a directory.  Mirrors the
    skip-list used for Python-file collection (no hidden dirs, venvs,
    site-packages, ...).
    """
    if root.is_file():
        if is_availability_text_file(root):
            yield root
        return
    if not root.is_dir():
        return
    for child in sorted(root.rglob("*")):
        if not child.is_file() or child.is_symlink():
            continue
        parts = child.relative_to(root).parts
        if any(
            part.startswith(".")
            or part in (
                "__pycache__", "node_modules",
                "venv", ".venv", "env", ".env",
                "site-packages", ".tox", ".nox",
            )
            for part in parts
        ):
            continue
        if is_availability_text_file(child):
            yield child
