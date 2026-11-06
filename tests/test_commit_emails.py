"""scripts/check_commit_emails.py keeps personal email addresses off main."""

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
# Synthetic addresses, split so this file never holds a whole personal address
# (the check scans every line a PR adds).
GMAIL = "someone.else" + "@gmail.com"
WORK = "a.person" + "@unlimit.co.nz"


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
    diff: str | None = None,
    title: str = "Fix a thing",
    body: str = "",
    author: str = "someone",
) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "commits.jsonl"
    path.write_text("".join(json.dumps(c) + "\n" for c in commits), encoding="utf-8")
    args = [str(path)]
    if diff is not None:
        diff_path = tmp_path / "added.diff"
        diff_path.write_text(diff, encoding="utf-8")
        args.append(str(diff_path))
    env = {**os.environ, "PR_TITLE": title, "PR_BODY": body, "PR_AUTHOR": author}
    return subprocess.run(  # noqa: S603 - this interpreter running a repo script
        [sys.executable, str(SCRIPT), *args],
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
        _commit(author=NOREPLY + " "),
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
        # Outside contributors must use their noreply address too.
        (
            _commit(author="dev@example.com"),
            "author email is not a GitHub noreply address (another domain)",
        ),
        (_commit(author=""), "author email is not a GitHub noreply address (no domain)"),
        (_commit(author=None), "author email is not a GitHub noreply address (no domain)"),
        (
            _commit(author=f"x{NOREPLY}.evil.example"),
            "author email is not a GitHub noreply address",
        ),
        (
            _commit(message=f"Fix\n\nCo-authored-by: Someone <{GMAIL}>"),
            "abcdef1: commit message contains a personal address (gmail.com)",
        ),
        (
            _commit(message=f"Fix\n\n  Co-authored-by : A <{WORK.upper()}>"),
            "commit message contains a personal address (UNLIMIT.CO.NZ)",
        ),
        (
            _commit(message=f"Thanks {GMAIL}"),
            "commit message contains a personal address (gmail.com)",
        ),
        (
            _commit(message="x\n\nReviewed-by: B <b.c" + "@googlemail.com>"),
            "commit message contains a personal address (googlemail.com)",
        ),
        (
            _commit(message="x\n\nReported-by: C <c" + "@mail.unlimit.co.nz>"),
            "commit message contains a personal address (unlimit.co.nz)",
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
        diff=f"+++ b/README.md\n@@ -1,0 +1 @@\n+mail {GMAIL}\n",
        body=f"contact {GMAIL}",
    )
    assert result.returncode == 1
    assert GMAIL not in result.stderr + result.stdout
    assert WORK not in result.stderr + result.stdout


@pytest.mark.parametrize(("title", "body"), [(f"Thanks {GMAIL}", ""), ("Fix", f"cc {WORK}")])
def test_personal_address_in_title_or_body_fails(tmp_path: Path, title: str, body: str) -> None:
    result = _run(tmp_path, [_commit()], title=title, body=body)
    assert result.returncode == 1
    assert "PR title contains" in result.stderr or "PR body contains" in result.stderr


def test_domain_without_an_address_is_allowed(tmp_path: Path) -> None:
    text = "Blocks @gmail.com and @unlimit.co.nz addresses."
    result = _run(
        tmp_path,
        [_commit(message=text)],
        diff=f"+++ b/docs/x.md\n@@ -0,0 +1 @@\n+{text}\n",
        body=text,
    )
    assert result.returncode == 0, result.stderr


def test_dependabot_pr_body_is_not_checked(tmp_path: Path) -> None:
    result = _run(tmp_path, [_commit()], body=f"Release notes by {GMAIL}", author="dependabot[bot]")
    assert result.returncode == 0, result.stderr


def test_bot_commits_are_still_checked(tmp_path: Path) -> None:
    result = _run(tmp_path, [_commit(author=GMAIL)], author="dependabot[bot]")
    assert result.returncode == 1


DIFF = (
    "diff --git a/plugin/plugin.base.toml b/plugin/plugin.base.toml\n"
    "index 1111111..2222222 100644\n"
    "--- a/plugin/plugin.base.toml\n"
    "+++ b/plugin/plugin.base.toml\n"
    "@@ -3 +3 @@ name\n"
    f'-email = "{NOREPLY}"\n'
    f'+email = "{GMAIL}"\n'
    "@@ -10,0 +11,2 @@ x\n"
    "+fine line\n"
    f"+owner {WORK}\n"
    "diff --git a/old.txt b/old.txt\n"
    "deleted file mode 100644\n"
    "--- a/old.txt\n"
    "+++ /dev/null\n"
    "@@ -1 +0,0 @@\n"
    f"-gone {GMAIL}\n"
)


def test_added_lines_are_checked_by_file_and_line(tmp_path: Path) -> None:
    result = _run(tmp_path, [_commit()], diff=DIFF)
    assert result.returncode == 1
    assert "plugin/plugin.base.toml:3: adds a personal address (gmail.com)" in result.stderr
    assert "plugin/plugin.base.toml:12: adds a personal address (unlimit.co.nz)" in result.stderr
    # Removing an address is fine.
    assert "old.txt" not in result.stderr


def test_clean_diff_passes(tmp_path: Path) -> None:
    diff = "+++ b/a.py\n@@ -0,0 +1 @@\n+print('hi')\n"
    assert _run(tmp_path, [_commit()], diff=diff).returncode == 0


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


def test_other_bots_pr_body_is_checked(tmp_path: Path) -> None:
    result = _run(tmp_path, [_commit()], body=f"cc {GMAIL}", author="copilot-swe-agent[bot]")
    assert result.returncode == 1


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("j\u00f6" + "@gmail.com", "gmail.com"),  # non-ASCII local part
        ("a!" + "@gmail.com", "gmail.com"),
        ("someone\uff20" + "gmail.com", "gmail.com"),  # full-width at sign
        ("some\u200bone@" + "gmail.com", "gmail.com"),  # zero-width space
        ("mailto:x" + "@unlimit.co.nz", "unlimit.co.nz"),
        ("<x" + "@GMAIL.COM>", "GMAIL.COM"),
        ("Thanks x" + "@gmail.com.", "gmail.com"),  # end of a sentence
    ],
)
def test_address_forms_are_caught(tmp_path: Path, text: str, found: str) -> None:
    result = _run(tmp_path, [_commit()], body=f"see {text} please")
    assert result.returncode == 1
    assert f"PR body contains a personal address ({found})" in result.stderr


@pytest.mark.parametrize(
    "text",
    [
        'GMAIL = "someone" + "@gmail.com"',
        "domains such as `@gmail.com` and (@unlimit.co.nz)",
        "user@notgmail.com and x@unlimit.co.nz.example",
    ],
)
def test_split_or_lookalike_addresses_are_not_flagged(tmp_path: Path, text: str) -> None:
    result = _run(tmp_path, [_commit()], body=text)
    assert result.returncode == 0, result.stderr


def test_subdomain_label_is_never_printed(tmp_path: Path) -> None:
    result = _run(tmp_path, [_commit(author="x" + "@secretbox.unlimit.co.nz")])
    assert result.returncode == 1
    assert "(unlimit.co.nz)" in result.stderr
    assert "secretbox" not in result.stderr


def test_soft_hyphen_inside_an_address_is_caught(tmp_path: Path) -> None:
    result = _run(tmp_path, [_commit()], body="fake@gm" + chr(0xAD) + "ail.com")
    assert result.returncode == 1


def test_added_line_starting_with_plus_plus_is_checked(tmp_path: Path) -> None:
    diff = (
        "diff --git a/notes.md b/notes.md\n"
        "--- a/notes.md\n"
        "+++ b/notes.md\n"
        "@@ -1,0 +1,3 @@\n"
        "+ok\n"
        f"+++ {GMAIL}\n"
        f"+then {WORK}\n"
    )
    result = _run(tmp_path, [_commit()], diff=diff)
    assert result.returncode == 1
    assert "notes.md:2: adds a personal address (gmail.com)" in result.stderr
    assert "notes.md:3: adds a personal address (unlimit.co.nz)" in result.stderr


def test_removed_line_starting_with_dashes_is_not_a_header(tmp_path: Path) -> None:
    diff = (
        "diff --git a/a.md b/a.md\n"
        "--- a/a.md\n"
        "+++ b/a.md\n"
        "@@ -1 +1 @@\n"
        "--- old rule\n"
        f"+new {GMAIL}\n"
    )
    result = _run(tmp_path, [_commit()], diff=diff)
    assert "a.md:1: adds a personal address (gmail.com)" in result.stderr


def test_no_newline_marker_does_not_shift_line_numbers(tmp_path: Path) -> None:
    diff = (
        "diff --git a/c.txt b/c.txt\n"
        "--- a/c.txt\n"
        "+++ b/c.txt\n"
        "@@ -3 +3 @@\n"
        "-old\n"
        "\\ No newline at end of file\n"
        f"+new {GMAIL}\n"
    )
    result = _run(tmp_path, [_commit()], diff=diff)
    assert "c.txt:3: adds a personal address (gmail.com)" in result.stderr


def test_quoted_diff_path_is_unquoted(tmp_path: Path) -> None:
    diff = f'diff --git "a/x y.md" "b/x y.md"\n+++ "b/x y.md"\n@@ -0,0 +1 @@\n+{GMAIL}\n'
    result = _run(tmp_path, [_commit()], diff=diff)
    assert "x y.md:1: adds a personal address (gmail.com)" in result.stderr
