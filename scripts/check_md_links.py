"""Check repo-relative links in tracked Markdown files (offline).

Covers inline links and images, reference-style link definitions, and HTML
href/src attributes. Links with a URL scheme (https:, mailto:, ...) and
in-page anchors are skipped; fragments on file links are ignored. Fenced code
blocks and inline code spans are not scanned. A relative link fails when its
target file or directory does not exist. Exits non-zero on any broken link.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
INLINE = re.compile(r"\]\(\s*(<[^>]*>|[^)\s]+)")
REFERENCE_DEF = re.compile(r"^\s{0,3}\[(?!\^)[^\]]+\]:\s*(<[^>]*>|\S+)")
HTML_ATTR = re.compile(r"""\b(?:href|src)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
CODE_SPAN = re.compile(r"(`+).*?\1")
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def tracked_markdown() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout
    return [ROOT / line for line in out.splitlines() if line]


def targets(line: str) -> list[str]:
    text = CODE_SPAN.sub("", line)
    found = INLINE.findall(text) + HTML_ATTR.findall(text)
    ref = REFERENCE_DEF.match(text)
    if ref:
        found.append(ref.group(1))
    return [t.strip("<>") for t in found]


def broken_links(path: Path) -> list[str]:
    broken: list[str] = []
    fence: str | None = None
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        opener = FENCE.match(line)
        if opener:
            marker, rest = opener.group(1), opener.group(2).strip()
            if fence is None:
                fence = marker
                continue
            if marker[0] == fence[0] and len(marker) >= len(fence) and not rest:
                fence = None
            continue
        if fence is not None:
            continue
        for target in targets(line):
            if not target or target.startswith("#") or SCHEME.match(target):
                continue
            rel = unquote(target.split("#", 1)[0])
            resolved = ROOT / rel.lstrip("/") if rel.startswith("/") else path.parent / rel
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
