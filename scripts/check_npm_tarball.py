"""Check that a packed npm tarball holds exactly the launcher files, unchanged.

Usage: check_npm_tarball.py <tarball.tgz> <version> [source-dir]

The tarball must hold package.json, README.md, LICENSE, NOTICE, the two bin
scripts and lib/launch.js from the source directory (default: npm/), each a
regular file, and nothing else. package.json is compared as JSON and must
carry the given version; every other file must be byte-identical. Exits
non-zero with one line per difference.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = (
    "package.json",
    "README.md",
    "LICENSE",
    "NOTICE",
    "bin/nz-openbank-mcp.js",
    "bin/nz-openbank-mcp-http.js",
    "lib/launch.js",
)
PREFIX = "package/"
WITH_SOURCE = 3  # argument count when a source directory is given


def differences(tarball: Path, version: str, source: Path) -> list[str]:
    problems: list[str] = []
    got: dict[str, bytes] = {}
    with tarfile.open(tarball, "r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        problems += [f"duplicate entry: {n}" for n in sorted(set(names)) if names.count(n) > 1]
        for member in members:
            if not member.name.startswith(PREFIX):
                problems.append(f"entry outside {PREFIX}: {member.name}")
            elif not member.isfile():
                problems.append(f"not a regular file: {member.name}")
            else:
                extracted = archive.extractfile(member)
                got[member.name.removeprefix(PREFIX)] = extracted.read() if extracted else b""
    problems += [f"unexpected file: {name}" for name in sorted(set(got) - set(FILES))]
    problems += [f"missing: {name}" for name in FILES if name not in got]
    for name in FILES:
        if name not in got:
            continue
        want = (source / name).read_bytes()
        if name == "package.json":
            packed = json.loads(got[name])
            if packed.get("version") != version:
                problems.append(f"package.json version {packed.get('version')!r} != {version!r}")
            if packed != json.loads(want):
                problems.append("package.json differs from the source package.json")
        elif hashlib.sha256(got[name]).digest() != hashlib.sha256(want).digest():
            problems.append(f"content differs from source: {name}")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) not in (WITH_SOURCE - 1, WITH_SOURCE):
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    tarball, version = Path(argv[0]), argv[1]
    source = Path(argv[2]) if len(argv) == WITH_SOURCE else ROOT / "npm"
    problems = differences(tarball, version, source)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"tarball ok: {tarball.name} matches {source.name}/ at version {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
