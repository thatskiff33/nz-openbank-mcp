"""Committed host manifests must match what plugin/plugin.base.toml generates."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - this interpreter running a repo script
        [sys.executable, str(ROOT / "scripts" / script), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_generated_manifests_are_up_to_date() -> None:
    result = _run("sync_plugin_manifests.py", "--check")
    assert result.returncode == 0, result.stderr


def test_packaging_checks_pass() -> None:
    result = _run("check_packaging.py")
    assert result.returncode == 0, result.stderr
