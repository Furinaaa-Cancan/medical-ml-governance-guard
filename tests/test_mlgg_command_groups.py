"""Smoke tests for W28-S0 ``COMMAND_GROUPS``.

The dispatcher (``scripts.orchestration.mlgg.COMMANDS``) and the
organizational grouping (``COMMAND_GROUPS``) must stay in sync so that
``--help`` never silently drops a subcommand. These tests catch the
two failure modes:

1. A new command was added to ``COMMANDS`` but not assigned to a group
   (would render under the "[other]" fallback header in --help).
2. A command name in ``COMMAND_GROUPS`` no longer exists in ``COMMANDS``
   (would render as a dangling entry in --help).
"""
from __future__ import annotations

from scripts.orchestration.mlgg import (
    COMMANDS,
    COMMAND_GROUPS,
    COMMAND_GROUP_DESCRIPTIONS,
    _render_grouped_command_help,
)


def test_every_command_is_in_exactly_one_group():
    """Each COMMANDS entry must appear in exactly one COMMAND_GROUPS list."""
    placements: dict[str, list[str]] = {}
    for group_name, members in COMMAND_GROUPS.items():
        for name in members:
            placements.setdefault(name, []).append(group_name)

    missing = sorted(set(COMMANDS) - set(placements))
    assert not missing, (
        f"COMMAND_GROUPS missing entries for: {missing}. "
        "Add each to exactly one group in scripts/orchestration/mlgg.py."
    )

    duplicated = {name: groups for name, groups in placements.items() if len(groups) > 1}
    assert not duplicated, (
        f"COMMAND_GROUPS duplicates: {duplicated}. "
        "Each command must live in exactly one group."
    )


def test_no_orphan_group_entries():
    """COMMAND_GROUPS must not reference commands absent from COMMANDS."""
    for group_name, members in COMMAND_GROUPS.items():
        for name in members:
            assert name in COMMANDS, (
                f"COMMAND_GROUPS[{group_name!r}] references "
                f"{name!r}, which is not in COMMANDS."
            )


def test_every_group_has_a_description():
    """Each group key needs a human-readable description for --help."""
    for group_name in COMMAND_GROUPS:
        assert group_name in COMMAND_GROUP_DESCRIPTIONS, (
            f"COMMAND_GROUP_DESCRIPTIONS missing entry for {group_name!r}."
        )
        assert COMMAND_GROUP_DESCRIPTIONS[group_name].strip(), (
            f"Group {group_name!r} has an empty description."
        )


def test_render_grouped_help_contains_every_command():
    """The rendered --help block must list every COMMANDS entry exactly once."""
    rendered = _render_grouped_command_help()
    for name in COMMANDS:
        # Match "    - <name>:" to avoid matching substrings of other names
        # (e.g. "audit" being a prefix of "audit-report").
        needle = f"    - {name}:"
        count = rendered.count(needle)
        assert count == 1, (
            f"Command {name!r} appears {count} times in --help (expected 1). "
            f"Block:\n{rendered}"
        )
