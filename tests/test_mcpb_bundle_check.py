"""scripts/check_mcpb_bundle.py refuses any bundle that differs from mcpb/ (CI-07)."""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_mcpb_bundle.py"
MCPB = ROOT / "mcpb"


def _pack(
    path: Path,
    *,
    extra: dict[str, bytes] | None = None,
    drop: str | None = None,
    change: dict[str, bytes] | None = None,
) -> Path:
    """Zip mcpb/ the way the packer does: manifest re-serialised, *.md left out."""
    files = {
        "manifest.json": json.dumps(json.loads((MCPB / "manifest.json").read_bytes())).encode(),
        "icon.png": (MCPB / "icon.png").read_bytes(),
    }
    files.update(change or {})
    files.update(extra or {})
    if drop:
        files.pop(drop)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def _run(bundle: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - runs the repo's own script
        [sys.executable, str(SCRIPT), str(bundle), *extra],
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_faithful_bundle_passes(tmp_path: Path) -> None:
    result = _run(_pack(tmp_path / "ok.mcpb"))
    assert result.returncode == 0, result.stderr
    assert "bundle ok" in result.stdout


def test_an_extra_file_fails(tmp_path: Path) -> None:
    result = _run(_pack(tmp_path / "x.mcpb", extra={"server/run.js": b"evil()"}))
    assert result.returncode == 1
    assert "unexpected file in bundle: server/run.js" in result.stderr


def test_a_missing_file_fails(tmp_path: Path) -> None:
    result = _run(_pack(tmp_path / "x.mcpb", drop="icon.png"))
    assert result.returncode == 1
    assert "missing from bundle: icon.png" in result.stderr


def test_changed_content_fails(tmp_path: Path) -> None:
    result = _run(_pack(tmp_path / "x.mcpb", change={"icon.png": b"not the icon"}))
    assert result.returncode == 1
    assert "content differs from source: icon.png" in result.stderr


def test_a_changed_manifest_fails(tmp_path: Path) -> None:
    manifest = json.loads((MCPB / "manifest.json").read_bytes())
    manifest["server"]["mcp_config"]["command"] = "sh"
    result = _run(
        _pack(tmp_path / "x.mcpb", change={"manifest.json": json.dumps(manifest).encode()})
    )
    assert result.returncode == 1
    assert "manifest.json differs" in result.stderr


def test_ignore_file_comments_and_custom_source(tmp_path: Path) -> None:
    source = tmp_path / "src"
    (source / "docs").mkdir(parents=True)
    (source / ".mcpbignore").write_text("# notes\n\ndocs/*\n")
    (source / "manifest.json").write_text("{}")
    (source / "docs" / "guide.txt").write_text("left out")
    bundle = tmp_path / "b.mcpb"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("manifest.json", "{ }")
        archive.writestr("assets/", "")
    assert _run(bundle, str(source)).returncode == 0


def test_source_without_ignore_file(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "manifest.json").write_text("{}")
    bundle = tmp_path / "b.mcpb"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("manifest.json", "{}")
    assert _run(bundle, str(source)).returncode == 0


def test_wrong_arguments_print_usage() -> None:
    result = subprocess.run(  # noqa: S603 - runs the repo's own script
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 2
    assert "Usage" in result.stderr
