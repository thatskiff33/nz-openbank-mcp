"""Fail a pull request that would publish a personal email address.

Checks every commit in the PR: the author and committer emails must be GitHub
noreply addresses, and no Co-authored-by or Signed-off-by trailer may name a
personal address. The PR title and body are checked for personal addresses
too, except on PRs opened by a bot, whose bodies quote upstream release notes.

Input is one JSON object per line ({"sha", "author", "committer", "message"}),
as produced by `gh api --paginate repos/O/R/pulls/N/commits --jq ...`. The PR
title, body and author type come from PR_TITLE, PR_BODY and PR_AUTHOR_TYPE.
Messages name only the domain of an offending address, never the address, since
CI logs are public. Exits non-zero on any finding.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# GitHub's per-user noreply form (also used by bots such as dependabot[bot]),
# and the address GitHub uses as committer for web and squash commits.
NOREPLY = re.compile(r"[^@\s]+@users\.noreply\.github\.com", re.IGNORECASE)
ALLOWED = {"noreply@github.com"}
PERSONAL = re.compile(r"[A-Za-z0-9._%+-]+@(gmail\.com|unlimit\.co\.nz)\b", re.IGNORECASE)
TRAILER = re.compile(r"(?im)^(?:co-authored-by|signed-off-by):.*$")
# The commits endpoint returns at most 250 commits for a PR.
MAX_COMMITS = 250
FIX = (
    "To fix: set `git config user.email <id>+<login>@users.noreply.github.com`, then "
    "rewrite the branch, for example `git rebase --exec 'git commit --amend --no-edit "
    "--reset-author' origin/main`, and force-push. Edit the PR title or body to remove "
    "any personal address."
)


def domain(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower() if "@" in address else "no domain"


def is_noreply(address: str) -> bool:
    address = address.strip()
    return address.lower() in ALLOWED or NOREPLY.fullmatch(address) is not None


def check_commits(lines: list[str]) -> list[str]:
    problems: list[str] = []
    commits = [json.loads(line) for line in lines if line.strip()]
    if not commits:
        problems.append("no commits were read for this pull request")
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
        for trailer in TRAILER.findall(str(commit.get("message") or "")):
            for match in PERSONAL.finditer(trailer):
                name = trailer.split(":", 1)[0]
                problems.append(f"{sha}: {name} trailer names a personal address ({match[1]})")
    return problems


def check_text(label: str, text: str) -> list[str]:
    return [f"PR {label} contains a personal address ({m[1]})" for m in PERSONAL.finditer(text)]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: check_commit_emails.py COMMITS.jsonl", file=sys.stderr)
        return 2
    problems = check_commits(Path(args[0]).read_text(encoding="utf-8").splitlines())
    if os.environ.get("PR_AUTHOR_TYPE", "") != "Bot":
        problems += check_text("title", os.environ.get("PR_TITLE", ""))
        problems += check_text("body", os.environ.get("PR_BODY", ""))
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        print(FIX, file=sys.stderr)
        return 1
    print("emails ok: every commit uses a GitHub noreply address")
    return 0


if __name__ == "__main__":
    sys.exit(main())
