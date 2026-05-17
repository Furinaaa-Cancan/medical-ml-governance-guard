"""W28-S1 tests for the ``mlgg-review`` console-script shim.

The shim must:
- Allow exactly the commands in COMMAND_GROUPS["review"].
- Reject any other command with a clear pointer back to ``mlgg`` and
  exit code 2 (argparse-style usage error).
- Render a focused help block listing only the review commands.

We mock ``main`` to avoid spawning subprocesses; the shim's only job
is argv-gating and delegation, so verifying the gate + delegation
contract is enough.
"""
from __future__ import annotations

import sys
from unittest import mock

import pytest

from scripts.orchestration.mlgg import (
    COMMAND_GROUPS,
    review_cli_main,
)


def _run_shim(argv: list[str]):
    """Call review_cli_main with ``argv`` and capture SystemExit + main delegation."""
    with mock.patch.object(sys, "argv", ["mlgg-review", *argv]), \
         mock.patch("scripts.orchestration.mlgg.main", return_value=0) as mocked_main:
        with pytest.raises(SystemExit) as exc:
            review_cli_main()
    return exc.value.code, mocked_main


@pytest.mark.parametrize("cmd", list(COMMAND_GROUPS["review"]))
def test_review_shim_allows_every_review_command(cmd):
    """Every command in COMMAND_GROUPS["review"] must reach main()."""
    code, mocked_main = _run_shim([cmd, "--help"])
    assert code == 0
    assert mocked_main.called, (
        f"mlgg-review {cmd}: shim must delegate to main(), but main() was not invoked"
    )


@pytest.mark.parametrize("cmd", ["workflow", "strict", "train", "authority", "doctor"])
def test_review_shim_rejects_governance_commands(cmd, capsys):
    """Governance commands must exit 2 with a stderr pointer back to mlgg."""
    with mock.patch.object(sys, "argv", ["mlgg-review", cmd]), \
         mock.patch("scripts.orchestration.mlgg.main") as mocked_main:
        with pytest.raises(SystemExit) as exc:
            review_cli_main()
    assert exc.value.code == 2, (
        f"Rejected commands must exit 2 (argparse-style usage error), got {exc.value.code}"
    )
    assert not mocked_main.called, (
        f"main() must not be invoked when shim rejects {cmd!r}"
    )
    stderr = capsys.readouterr().err
    assert "mlgg-review" in stderr
    assert cmd in stderr
    assert "mlgg " in stderr, "rejection must point user back to the full mlgg entry"


def test_review_shim_unknown_command_rejected(capsys):
    """A command that doesn't exist in COMMANDS at all is still rejected."""
    with mock.patch.object(sys, "argv", ["mlgg-review", "nonexistent-subcommand"]), \
         mock.patch("scripts.orchestration.mlgg.main") as mocked_main:
        with pytest.raises(SystemExit) as exc:
            review_cli_main()
    assert exc.value.code == 2
    assert not mocked_main.called
    assert "nonexistent-subcommand" in capsys.readouterr().err


def test_review_shim_help_lists_only_review_commands(capsys):
    """`mlgg-review --help` must list every review command and no others."""
    with mock.patch.object(sys, "argv", ["mlgg-review", "--help"]):
        with pytest.raises(SystemExit) as exc:
            review_cli_main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    # Every review command appears with leading "- " marker
    for name in COMMAND_GROUPS["review"]:
        assert f"- {name}:" in out, f"help text missing review command {name!r}"
    # Spot-check a few governance commands are NOT in the help body
    for forbidden in ("workflow", "strict", "train", "doctor"):
        assert f"- {forbidden}:" not in out, (
            f"help text leaks governance command {forbidden!r}"
        )
    # Help must point at full mlgg for governance work
    assert "mlgg --help" in out or "PRODUCTS.md" in out


def test_review_shim_no_args_shows_help(capsys):
    """No subcommand → show the focused help (don't crash, don't exit 2)."""
    with mock.patch.object(sys, "argv", ["mlgg-review"]):
        with pytest.raises(SystemExit) as exc:
            review_cli_main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "review product line" in out
