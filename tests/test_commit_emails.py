"""scripts/check_commit_emails.py refuses personal email addresses in a PR."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_commit_emails.py"
NOREPLY = "12345+someone@users.noreply.github.com"
# Synthetic addresses only; the real ones must never appear in the repo.
GMAIL = "someone.else@gmail.com"
WORK = "a.person@unlimit.co.nz"


def _commit(**overrides: Any) -> dict[str, Any]:
    commit = {
        "sha": "abcdef1234567890",
        "author": NOREPLY,
        "committer": "noreply@github.com",
        "message": "Fix a thing\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
    }
    commit.update(overrides)
    return commit


def _run(
    tmp_path: Path,
    commits: list[dict[str, Any]],
    *,
    title: str = "Fix a thing",
    body: str = "",
    author_type: str = "User",
) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "commits.jsonl"
    path.write_text("".join(json.dumps(c) + "\n" for c in commits), encoding="utf-8")
    env = {
        **os.environ,
        "PR_TITLE": title,
        "PR_BODY": body,
        "PR_AUTHOR_TYPE": author_type,
    }
    return subprocess.run(  # noqa: S603 - this interpreter running a repo script
        [sys.executable, str(SCRIPT), str(path)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


@pytest.mark.parametrize(
    "commit",
    [
        _commit(),
        _commit(author="49699333+dependabot[bot]@users.noreply.github.com"),
        _commit(author="41898282+github-actions[bot]@users.noreply.github.com"),
        _commit(committer="NoReply@GitHub.com"),
        _commit(message="Bump x\n\nSigned-off-by: dependabot[bot] <support@github.com>"),
    ],
)
def test_noreply_commits_pass(tmp_path: Path, commit: dict[str, Any]) -> None:
    result = _run(tmp_path, [commit])
    assert result.returncode == 0, result.stderr
    assert "emails ok" in result.stdout


@pytest.mark.parametrize(
    ("commit", "message"),
    [
        (
            _commit(author=GMAIL),
            "abcdef1: author email is not a GitHub noreply address (gmail.com)",
        ),
        (
            _commit(committer=WORK),
            "abcdef1: committer email is not a GitHub noreply address (unlimit.co.nz)",
        ),
        (
            _commit(author="dev@example.com"),
            "author email is not a GitHub noreply address (example.com)",
        ),
        (_commit(author=""), "author email is not a GitHub noreply address (no domain)"),
        (
            _commit(author=f"x{NOREPLY}.evil.example"),
            "author email is not a GitHub noreply address",
        ),
        (
            _commit(message=f"Fix\n\nCo-authored-by: Someone <{GMAIL}>"),
            "abcdef1: Co-authored-by trailer names a personal address (gmail.com)",
        ),
        (
            _commit(message=f"Fix\n\nSigned-off-by: A Person <{WORK.upper()}>"),
            "Signed-off-by trailer names a personal address (UNLIMIT.CO.NZ)",
        ),
    ],
)
def test_personal_or_unknown_addresses_fail(
    tmp_path: Path, commit: dict[str, Any], message: str
) -> None:
    result = _run(tmp_path, [_commit(), commit])
    assert result.returncode == 1
    assert message in result.stderr
    assert "To fix" in result.stderr


def test_addresses_are_never_printed(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [_commit(author=GMAIL, message=f"x\n\nCo-authored-by: A <{WORK}>")],
        body=f"contact {GMAIL}",
    )
    assert result.returncode == 1
    assert GMAIL not in result.stderr + result.stdout
    assert WORK not in result.stderr + result.stdout


def test_address_in_message_body_outside_a_trailer_is_allowed(tmp_path: Path) -> None:
    # Only trailers are checked; prose may quote an address deliberately.
    result = _run(tmp_path, [_commit(message=f"Fix\n\nReported upstream by {GMAIL}.")])
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(("title", "body"), [(f"Thanks {GMAIL}", ""), ("Fix", f"cc {WORK}")])
def test_personal_address_in_title_or_body_fails(tmp_path: Path, title: str, body: str) -> None:
    result = _run(tmp_path, [_commit()], title=title, body=body)
    assert result.returncode == 1
    assert "PR title contains" in result.stderr or "PR body contains" in result.stderr


def test_domain_without_an_address_is_allowed_in_the_body(tmp_path: Path) -> None:
    result = _run(tmp_path, [_commit()], body="Blocks @gmail.com and @unlimit.co.nz addresses.")
    assert result.returncode == 0, result.stderr


def test_bot_pr_body_is_not_checked(tmp_path: Path) -> None:
    result = _run(tmp_path, [_commit()], body=f"Release notes by {GMAIL}", author_type="Bot")
    assert result.returncode == 0, result.stderr


def test_bot_commits_are_still_checked(tmp_path: Path) -> None:
    result = _run(tmp_path, [_commit(author=GMAIL)], author_type="Bot")
    assert result.returncode == 1


def test_no_commits_fails(tmp_path: Path) -> None:
    result = _run(tmp_path, [])
    assert result.returncode == 1
    assert "no commits were read" in result.stderr


def test_too_many_commits_fails(tmp_path: Path) -> None:
    result = _run(tmp_path, [_commit()] * 250)
    assert result.returncode == 1
    assert "the API lists at most 250" in result.stderr


def test_wrong_arguments_print_usage(tmp_path: Path) -> None:
    result = subprocess.run(  # noqa: S603 - this interpreter running a repo script
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 2
    assert "usage:" in result.stderr


def test_pyproject_authors_have_no_email() -> None:
    """Package metadata on PyPI must not carry an email address."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    for field in ("authors", "maintainers"):
        for person in project.get(field, []):
            assert "email" not in person, f"{field} entry has an email"
            assert "@" not in person.get("name", ""), f"{field} name contains an address"
