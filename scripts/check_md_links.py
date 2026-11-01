"""Check repo-relative links in tracked Markdown files (offline).

External URLs, mailto links and in-page anchors are skipped. A relative link
fails when its target file or directory does not exist. Exits non-zero on any
broken link.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
FENCE = re.compile(r"^\s*(```|~~~)")
SKIP = ("http://", "https://", "mailto:", "#")


def tracked_markdown() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout
    return [ROOT / line for line in out.splitlines() if line]


def broken_links(path: Path) -> list[str]:
    broken: list[str] = []
    in_fence = False
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for target in LINK.findall(line):
            if target.startswith(SKIP):
                continue
            rel = unquote(target.split("#", 1)[0])
            if not rel:
                continue
            resolved = (ROOT / rel.lstrip("/")) if rel.startswith("/") else path.parent / rel
            if not resolved.exists():
                broken.append(f"{path.relative_to(ROOT)}:{lineno}: {target}")
    return broken


def main() -> int:
    files = tracked_markdown()
    broken = [b for path in files for b in broken_links(path)]
    for item in broken:
        print(f"broken link: {item}", file=sys.stderr)
    if not broken:
        print(f"links ok: {len(files)} Markdown files")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
