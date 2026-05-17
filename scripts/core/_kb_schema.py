"""Peer-review KB concern schema + soft-deprecate contract (W20-C3 / W17-C5).

Why this exists
---------------
``references/case-studies/peer-review-kb.json`` is referenced by external
artifacts the loader does not know about:

* ``references/case-studies/rag-eval-set.yaml`` (RAG eval ground truth)
* ``references/retrieval_eval/scenarios.json`` (retrieval eval scenarios)
* test fixtures under ``tests/``

When a concern is **hard-deleted** from the KB (the file is rewritten so the
``concern_id`` simply disappears), every external reference becomes a silent
dangling pointer. W17-C5 found ``PR-040-C01`` in that exact state: still
referenced by ``rag-eval-set.yaml`` but absent from the KB, with no warning
emitted anywhere.

The fix is a contract change, not a one-off cleanup:

* Concerns may be **soft-deprecated** (``deprecated: true``) but the
  ``concern_id`` must remain in the KB so external references continue to
  resolve (to a tombstone with a reason and an optional ``superseded_by``).
* Hard-deleting a concern_id is permitted only if no external artifact
  references it (validated by ``scripts/diagnostics/check_kb_no_dangling.py``).

Schema is enforced via plain-dict validation (consistent with the rest of
``scripts/core/`` — neither Pydantic nor jsonschema is used in this project).

Public API
----------
* :func:`validate_concern` — raises :class:`KBSchemaError` on contract
  violation; returns ``None`` on success.
* :func:`concern_can_be_deleted` — boolean helper used by the dangling-ref
  checker to decide whether a concern_id may be hard-removed.
* :func:`is_iso_date` — narrow ISO-8601 date guard (``YYYY-MM-DD``); also
  accepts datetimes with timezone info.
* :data:`REQUIRED_CONCERN_FIELDS`, :data:`REQUIRED_DEPRECATED_FIELDS`,
  :data:`CANONICAL_SEVERITIES` — exported for tests and downstream gates.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, Iterable, Optional


REQUIRED_CONCERN_FIELDS = ("concern_id", "concern_text", "severity", "mlgg_gates")
"""Fields every concern must carry, deprecated or not."""

REQUIRED_DEPRECATED_FIELDS = ("deprecated_at", "deprecated_reason")
"""Additional fields required when ``deprecated`` is true.

``superseded_by`` is intentionally optional — a concern can be retired without
being replaced (e.g. retracted paper, fabricated DOI).
"""

CANONICAL_SEVERITIES = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW"})
"""Severity allowlist — matches ``scripts/diagnostics/kb_hygiene_check.py``."""

# ``YYYY-MM-DD`` or ISO-8601 datetime (with or without timezone).
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CONCERN_ID_RE = re.compile(r"^PR-\d+-C\d+$")


class KBSchemaError(ValueError):
    """Raised when a concern record violates the soft-deprecate contract."""


def is_iso_date(value: Any) -> bool:
    """Return ``True`` if ``value`` is a plain ISO date or ISO datetime string.

    Accepts ``date`` / ``datetime`` instances as well so callers loading from
    YAML (where dates may auto-parse) don't have to coerce first.
    """
    if isinstance(value, (date, datetime)):
        return True
    if not isinstance(value, str):
        return False
    if _ISO_DATE_RE.match(value):
        try:
            date.fromisoformat(value)
            return True
        except ValueError:
            return False
    # Allow full ISO datetime (with timezone, ``T`` separator).
    try:
        # ``fromisoformat`` accepts ``YYYY-MM-DDTHH:MM:SS[+HH:MM]`` on 3.11+.
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate_concern(record: Dict[str, Any]) -> None:
    """Validate a single concern record against the contract.

    Parameters
    ----------
    record
        A ``reviewer_concerns[i]`` dict from peer-review-kb.json.

    Raises
    ------
    KBSchemaError
        On any contract violation. The exception message names the offending
        field so the checker can surface it directly to authors.
    """
    if not isinstance(record, dict):
        raise KBSchemaError(f"concern record must be a dict, got {type(record).__name__}")

    # Required fields — always.
    for field in REQUIRED_CONCERN_FIELDS:
        if field not in record:
            raise KBSchemaError(
                f"concern missing required field '{field}' "
                f"(concern_id={record.get('concern_id', '?')})"
            )

    concern_id = record.get("concern_id")
    if not isinstance(concern_id, str) or not concern_id:
        raise KBSchemaError("concern_id must be a non-empty string")
    if not _CONCERN_ID_RE.match(concern_id):
        # Don't fail-loud on legacy / synth ids — they're allowed by other
        # checks (test_no_concern_id_starts_with_synth_unless_flagged). Skip
        # the regex enforcement here to stay narrowly focused on the
        # deprecate contract.
        pass

    severity = record.get("severity")
    if severity not in CANONICAL_SEVERITIES:
        raise KBSchemaError(
            f"concern {concern_id} has non-canonical severity '{severity}' "
            f"(allowed: {sorted(CANONICAL_SEVERITIES)})"
        )

    mlgg_gates = record.get("mlgg_gates")
    if not isinstance(mlgg_gates, list):
        raise KBSchemaError(
            f"concern {concern_id} mlgg_gates must be a list, "
            f"got {type(mlgg_gates).__name__}"
        )

    concern_text = record.get("concern_text")
    if not isinstance(concern_text, str) or not concern_text.strip():
        raise KBSchemaError(f"concern {concern_id} concern_text must be a non-empty string")

    # Deprecate contract — only enforced when the flag is present.
    deprecated = record.get("deprecated", False)
    if not isinstance(deprecated, bool):
        raise KBSchemaError(
            f"concern {concern_id} 'deprecated' must be a bool, "
            f"got {type(deprecated).__name__}"
        )

    if deprecated:
        for field in REQUIRED_DEPRECATED_FIELDS:
            if field not in record or record[field] in (None, ""):
                raise KBSchemaError(
                    f"deprecated concern {concern_id} missing required field "
                    f"'{field}' (required when deprecated=true)"
                )
        if not is_iso_date(record["deprecated_at"]):
            raise KBSchemaError(
                f"deprecated concern {concern_id} 'deprecated_at' must be an "
                f"ISO-8601 date (YYYY-MM-DD), got {record['deprecated_at']!r}"
            )
        reason = record["deprecated_reason"]
        if not isinstance(reason, str) or not reason.strip():
            raise KBSchemaError(
                f"deprecated concern {concern_id} 'deprecated_reason' must be a "
                f"non-empty string"
            )
        # superseded_by is optional but must be a string if present.
        superseded_by = record.get("superseded_by")
        if superseded_by is not None and not isinstance(superseded_by, str):
            raise KBSchemaError(
                f"deprecated concern {concern_id} 'superseded_by' must be a "
                f"string or null, got {type(superseded_by).__name__}"
            )


def concern_can_be_deleted(
    record: Dict[str, Any],
    external_refs: Optional[Iterable[str]] = None,
) -> bool:
    """Decide whether a concern may be hard-removed from the KB.

    A concern is hard-deletable only when **no external artifact** still
    references its ``concern_id``. Otherwise the caller must soft-deprecate
    (set ``deprecated=true`` + required fields) so the tombstone keeps the
    external pointer alive.

    Parameters
    ----------
    record
        A ``reviewer_concerns[i]`` dict from peer-review-kb.json. Must contain
        a ``concern_id``.
    external_refs
        Iterable of concern_ids referenced by external artifacts
        (rag-eval-set.yaml, scenarios.json, test fixtures, …). Typically
        produced by :func:`scripts.diagnostics.check_kb_no_dangling.collect_external_refs`.

    Returns
    -------
    bool
        ``True`` if no external reference exists for this concern (safe to
        hard-delete). ``False`` otherwise — caller must soft-deprecate.
    """
    concern_id = record.get("concern_id")
    if not concern_id:
        # Without an id we cannot reason about external refs; refuse deletion.
        return False
    if external_refs is None:
        return True
    return concern_id not in set(external_refs)
