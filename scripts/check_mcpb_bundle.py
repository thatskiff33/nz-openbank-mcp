"""Check that a packed .mcpb holds exactly the files in mcpb/, unchanged.

Usage: check_mcpb_bundle.py <bundle.mcpb> [source-dir]

The expected set is every file under the source directory (default: mcpb/)
except `.mcpbignore` and the files its patterns exclude. The bundle must hold
that set and nothing else. manifest.json is compared as JSON, because the
packer may re-serialise it; every other file must be byte-identical. Exits
non-zero with one line per difference.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IGNORE_FILE = ".mcpbignore"
WITH_SOURCE = 2  # argument count when a source directory is given


def ignore_patterns(source: Path) -> list[str]:
    path = source / IGNORE_FILE
    if not path.is_file():
        return []
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def expected_files(source: Path) -> dict[str, bytes]:
    patterns = ignore_patterns(source)
    files: dict[str, bytes] = {}
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(source).as_posix()
        if rel == IGNORE_FILE:
            continue
        if any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(path.name, p) for p in patterns):
            continue
        files[rel] = path.read_bytes()
    return files


def differences(bundle: Path, source: Path) -> list[str]:
    want = expected_files(source)
    with zipfile.ZipFile(bundle) as archive:
        got = {
            info.filename: archive.read(info) for info in archive.infolist() if not info.is_dir()
        }
    problems = [f"unexpected file in bundle: {name}" for name in sorted(set(got) - set(want))]
    problems += [f"missing from bundle: {name}" for name in sorted(set(want) - set(got))]
    for name in sorted(set(want) & set(got)):
        if name == "manifest.json":
            if json.loads(got[name]) != json.loads(want[name]):
                problems.append("manifest.json differs from the source manifest")
        elif hashlib.sha256(got[name]).digest() != hashlib.sha256(want[name]).digest():
            problems.append(f"content differs from source: {name}")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) not in (1, WITH_SOURCE):
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    bundle = Path(argv[0])
    source = Path(argv[1]) if len(argv) == WITH_SOURCE else ROOT / "mcpb"
    problems = differences(bundle, source)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"bundle ok: {bundle.name} matches {source.name}/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
