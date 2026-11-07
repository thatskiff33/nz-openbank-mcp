"""scripts/check_npm_tarball.py refuses any tarball that differs from npm/."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_npm_tarball.py"
NPM = ROOT / "npm"
VERSION = json.loads((NPM / "package.json").read_text(encoding="utf-8"))["version"]
FILES = (
    "package.json",
    "README.md",
    "LICENSE",
    "NOTICE",
    "bin/nz-openbank-mcp.js",
    "bin/nz-openbank-mcp-http.js",
    "lib/launch.js",
)


def _pack(
    path: Path,
    *,
    change: dict[str, bytes] | None = None,
    drop: str | None = None,
    extra: list[tarfile.TarInfo] | None = None,
) -> Path:
    """Write a tarball laid out as npm pack does: every file under package/."""
    contents = {name: (NPM / name).read_bytes() for name in FILES if name != drop}
    contents.update(change or {})
    with tarfile.open(path, "w:gz") as archive:
        for name, data in contents.items():
            info = tarfile.TarInfo(f"package/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        for info in extra or []:
            archive.addfile(info, io.BytesIO(b"x" * info.size) if info.isfile() else None)
    return path


def _check(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - this interpreter running a repo script
        [sys.executable, str(SCRIPT), *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )


def _entry(name: str, kind: bytes = tarfile.REGTYPE, size: int = 1) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.size = size if kind == tarfile.REGTYPE else 0
    if kind == tarfile.SYMTYPE:
        info.linkname = "/etc/passwd"
    return info


def test_an_exact_pack_passes(tmp_path: Path) -> None:
    result = _check(_pack(tmp_path / "ok.tgz"), VERSION)
    assert result.returncode == 0, result.stderr
    assert f"at version {VERSION}" in result.stdout


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"drop": "NOTICE"}, "missing: NOTICE"),
        (
            {"change": {"lib/launch.js": b"// changed"}},
            "content differs from source: lib/launch.js",
        ),
        ({"change": {"package.json": b'{"name": "x"}'}}, "package.json differs from the source"),
        (
            {"extra": [_entry("package/test/launch.test.js")]},
            "unexpected file: test/launch.test.js",
        ),
        ({"extra": [_entry("package/lib/launch.js")]}, "duplicate entry: package/lib/launch.js"),
        ({"extra": [_entry("other/x.js")]}, "entry outside package/: other/x.js"),
        (
            {"extra": [_entry("package/bin/link", tarfile.SYMTYPE)]},
            "not a regular file: package/bin/link",
        ),
    ],
)
def test_a_changed_pack_is_refused(tmp_path: Path, kwargs: dict[str, object], message: str) -> None:
    result = _check(_pack(tmp_path / "bad.tgz", **kwargs), VERSION)  # type: ignore[arg-type]
    assert result.returncode == 1
    assert f"error: {message}" in result.stderr


def test_the_version_must_match(tmp_path: Path) -> None:
    result = _check(_pack(tmp_path / "ok.tgz"), "99.0.0")
    assert result.returncode == 1
    assert f"package.json version '{VERSION}' != '99.0.0'" in result.stderr


def test_a_bumped_source_is_compared_with_its_own_package_json(tmp_path: Path) -> None:
    """The CI dry run packs after moving npm/package.json to the next patch version."""
    source = tmp_path / "npm"
    for name in FILES:
        (source / name).parent.mkdir(parents=True, exist_ok=True)
        (source / name).write_bytes((NPM / name).read_bytes())
    bumped = json.loads((NPM / "package.json").read_text(encoding="utf-8"))
    bumped["version"] = "9.9.9"
    data = json.dumps(bumped).encode()
    (source / "package.json").write_bytes(data)
    tarball = _pack(tmp_path / "bumped.tgz", change={"package.json": data})
    result = _check(tarball, "9.9.9", source)
    assert result.returncode == 0, result.stderr


def test_usage_error_exits_2() -> None:
    result = _check("only-one-argument")
    assert result.returncode == 2
    assert "Usage:" in result.stderr
