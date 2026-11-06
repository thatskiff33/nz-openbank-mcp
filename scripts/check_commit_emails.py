"""Fail when a personal email address would land on main.

Checks a set of commits: the author and committer emails must be GitHub
noreply addresses, and no commit message may contain a personal address.
Optionally checks the lines a pull request adds (a unified diff), and the PR
title and body, except on Dependabot PRs, whose bodies quote upstream
release notes.

Run on every PR and, after merge, on each push to main, because GitHub writes
the squash commit at merge time with the merging account's commit email.
Anything pushed to a public branch is already public, so this keeps addresses
off main; account email settings are what keep them private.

Usage: check_commit_emails.py COMMITS.jsonl [ADDED.diff]
COMMITS.jsonl has one {"sha", "author", "committer", "message"} object per
line. The PR title, body and author login come from PR_TITLE, PR_BODY and
PR_AUTHOR. Messages name only the domain of an offending address, never
the address, since CI logs are public. Exits non-zero on any finding.
"""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from pathlib import Path

# GitHub's per-user noreply form (also used by bots such as dependabot[bot]),
# and the address GitHub uses as committer for web and squash commits.
NOREPLY = re.compile(r"[^@\s]+@users\.noreply\.github\.com", re.IGNORECASE)
ALLOWED = {"noreply@github.com"}
# Any local part (stopping at spaces, brackets, quotes and punctuation that
# cannot end one), at the personal domains and their subdomains.
# Group 1 is the base domain; a subdomain is matched but never reported, since
# its label could be anything.
PERSONAL_DOMAIN = r"(?:[a-z0-9-]+\.)*(gmail\.com|googlemail\.com|unlimit\.co\.nz)"
PERSONAL = re.compile(
    # Not followed by more of a domain name; a sentence-ending full stop is fine.
    rf"[^\s<>@\"'`(),;:\[\]]+@{PERSONAL_DOMAIN}(?![\w-]|\.[\w-])",
    re.IGNORECASE,
)
# The only bot whose PR bodies are skipped: they quote upstream release notes.
BODY_EXEMPT_AUTHORS = {"dependabot[bot]"}
# The commits endpoints return at most 250 commits.
MAX_COMMITS = 250
FIX = (
    "To fix: set `git config user.email <id>+<login>@users.noreply.github.com`, then "
    "rewrite the branch, for example `git rebase --exec 'git commit --amend --no-edit "
    "--reset-author' origin/main`, and force-push. Remove personal addresses from "
    "commit messages, changed files and the PR title and body. On main, turn on "
    '"Keep my email addresses private" for the account that merged.'
)


def normalise(text: str) -> str:
    """Fold full-width forms (NFKC) and drop invisible format characters (Cf)."""
    text = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def find_personal(text: str) -> list[str]:
    """Domains of the personal addresses in text."""
    return [match[1] for match in PERSONAL.finditer(normalise(text))]


def domain(address: str) -> str:
    """Name a personal domain; any other domain could identify a machine or person."""
    if "@" not in address:
        return "no domain"
    found = re.fullmatch(PERSONAL_DOMAIN, address.rsplit("@", 1)[-1].strip(), re.IGNORECASE)
    return found[1].lower() if found else "another domain"


def is_noreply(address: str) -> bool:
    address = address.strip()
    return address.lower() in ALLOWED or NOREPLY.fullmatch(address) is not None


def check_commits(lines: list[str]) -> list[str]:
    problems: list[str] = []
    commits = [json.loads(line) for line in lines if line.strip()]
    if not commits:
        problems.append("no commits were read")
    if len(commits) >= MAX_COMMITS:
        problems.append(
            f"{len(commits)} commits: the API lists at most {MAX_COMMITS}; split the PR"
        )
    for commit in commits:
        sha = str(commit.get("sha", ""))[:7]
        for role in ("author", "committer"):
            address = str(commit.get(role) or "")
            if not is_noreply(address):
                problems.append(
                    f"{sha}: {role} email is not a GitHub noreply address ({domain(address)})"
                )
        problems.extend(
            f"{sha}: commit message contains a personal address ({found})"
            for found in find_personal(str(commit.get("message") or ""))
        )
    return problems


def check_diff(diff: str) -> list[str]:
    """Personal addresses on lines the diff adds, by file and new line number."""
    problems: list[str] = []
    path, line_no = "?", 0
    # File headers (---, +++) only come before a file's first hunk; inside a
    # hunk, an added line "++ x" also starts with "+++ ".
    in_header = True
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            in_header = True
        elif in_header and line.startswith("+++ "):
            path = line[4:].strip('"')
            path = path.removeprefix("b/")
        elif line.startswith("@@"):
            in_header = False
            hunk = re.search(r"\+(\d+)", line)
            line_no = int(hunk[1]) if hunk else 0
        elif in_header or line.startswith(("-", "\\")):
            continue  # header lines, removed lines, "\ No newline at end of file"
        elif line.startswith("+"):
            problems.extend(
                f"{path}:{line_no}: adds a personal address ({found})"
                for found in find_personal(line)
            )
            line_no += 1
        else:
            line_no += 1
    return problems


def check_text(label: str, text: str) -> list[str]:
    return [f"PR {label} contains a personal address ({found})" for found in find_personal(text)]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) not in (1, 2):
        print("usage: check_commit_emails.py COMMITS.jsonl [ADDED.diff]", file=sys.stderr)
        return 2
    problems = check_commits(Path(args[0]).read_text(encoding="utf-8").splitlines())
    if len(args) > 1:
        problems += check_diff(Path(args[1]).read_text(encoding="utf-8", errors="replace"))
    if os.environ.get("PR_AUTHOR", "") not in BODY_EXEMPT_AUTHORS:
        problems += check_text("title", os.environ.get("PR_TITLE", ""))
        problems += check_text("body", os.environ.get("PR_BODY", ""))
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        print(FIX, file=sys.stderr)
        return 1
    print("emails ok: noreply commit emails and no personal addresses")
    return 0


if __name__ == "__main__":
    sys.exit(main())
