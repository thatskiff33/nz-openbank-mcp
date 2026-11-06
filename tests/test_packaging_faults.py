"""check_packaging.py catches each unsafe packaging change (CI-08).

Each test copies the tracked packaging files to a temporary checkout, injects
one fault, and expects the check to fail with a message naming it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_packaging.py"
PACKAGING_FILES = [
    "pyproject.toml",
    "Dockerfile",
    "server.json",
    "examples/claude_desktop_config.json",
    "mcpb/manifest.json",
    "src/nz_openbank_mcp/__init__.py",
    ".claude-plugin/marketplace.json",
    ".agents/plugins/marketplace.json",
    ".cursor-plugin/marketplace.json",
    ".grok-plugin/marketplace.json",
    "plugin/.claude-plugin/plugin.json",
    "plugin/.mcp.json",
    "plugin/.codex-plugin/plugin.json",
    "plugin/codex-mcp.json",
    "plugin/.cursor-plugin/plugin.json",
    "plugin/.grok-plugin/plugin.json",
    "plugin/grok-mcp.json",
]


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    for rel in PACKAGING_FILES:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)
    return tmp_path


def _check(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - this interpreter running a repo script
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def _edit_json(path: Path, change: Callable[[Any], None]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def _registry_env(data: Any, name: str) -> dict[str, Any]:
    return next(e for e in data["packages"][0]["environmentVariables"] if e["name"] == name)


def test_the_copied_checkout_passes(checkout: Path) -> None:
    result = _check(checkout)
    assert result.returncode == 0, result.stderr


def test_registry_read_only_default_must_stay_true(checkout: Path) -> None:
    _edit_json(
        checkout / "server.json",
        lambda d: _registry_env(d, "AKAHU_READ_ONLY").update(default="false"),
    )
    result = _check(checkout)
    assert result.returncode == 1
    assert "server.json: AKAHU_READ_ONLY default must be 'true'" in result.stderr


def test_registry_tokens_must_be_secret_without_default(checkout: Path) -> None:
    _edit_json(
        checkout / "server.json",
        lambda d: _registry_env(d, "AKAHU_USER_TOKEN").update(isSecret=False, default="x"),
    )
    result = _check(checkout)
    assert result.returncode == 1
    assert "server.json: AKAHU_USER_TOKEN must be isSecret" in result.stderr
    assert "AKAHU_USER_TOKEN is secret and must not have a default" in result.stderr


def test_sensitive_user_config_must_not_have_a_default(checkout: Path) -> None:
    _edit_json(
        checkout / "plugin/.claude-plugin/plugin.json",
        lambda d: d["userConfig"]["akahu_app_token"].update(default="app_token_x"),
    )
    result = _check(checkout)
    assert result.returncode == 1
    assert "akahu_app_token is sensitive and must not have a default" in result.stderr


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("AKAHU_READ_ONLY=true", "AKAHU_READ_ONLY=false"),
        ("AKAHU_AUTOMATION_BYPASS=false", "AKAHU_AUTOMATION_BYPASS=true"),
    ],
)
def test_dockerfile_must_keep_safe_defaults(checkout: Path, old: str, new: str) -> None:
    dockerfile = checkout / "Dockerfile"
    dockerfile.write_text(dockerfile.read_text(encoding="utf-8").replace(old, new), "utf-8")
    result = _check(checkout)
    assert result.returncode == 1
    assert f"Dockerfile: ENV must set {old} in the final stage" in result.stderr


@pytest.mark.parametrize(
    "extra",
    [
        "\nENV AKAHU_READ_ONLY=false\n",
        "\nENV AKAHU_AUTOMATION_BYPASS=true\n",
    ],
)
def test_dockerfile_later_override_is_caught(checkout: Path, extra: str) -> None:
    dockerfile = checkout / "Dockerfile"
    dockerfile.write_text(dockerfile.read_text(encoding="utf-8") + extra, "utf-8")
    result = _check(checkout)
    assert result.returncode == 1
    assert "Dockerfile: ENV must set" in result.stderr


def test_dockerfile_safe_env_only_in_build_stage_is_caught(checkout: Path) -> None:
    dockerfile = checkout / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")
    first_from = text.index("FROM ")
    second_from = text.index("FROM ", first_from + 1)
    final = text[second_from:]
    final = final.replace("AKAHU_READ_ONLY=true", "AKAHU_X=1")
    stage1 = text[:second_from] + "ENV AKAHU_READ_ONLY=true\n"
    dockerfile.write_text(stage1 + final, "utf-8")
    result = _check(checkout)
    assert result.returncode == 1
    assert "AKAHU_READ_ONLY=true in the final stage" in result.stderr


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        # uv sync building and installing the project itself.
        (
            "uv sync --frozen --no-dev --no-install-project --no-build",
            "uv sync --frozen --no-dev --no-editable",
            "uv sync needs --no-install-project and --no-build",
        ),
        (
            "uv sync --frozen --no-dev --no-install-project --no-build",
            "uv sync --frozen --no-dev --no-install-project",
            "uv sync needs --no-install-project and --no-build",
        ),
        (
            '--no-deps --no-build "$1"',
            '--no-deps "$1"',
            "pip install needs --no-build",
        ),
    ],
)
def test_dockerfile_must_not_build_the_package(
    checkout: Path, old: str, new: str, message: str
) -> None:
    dockerfile = checkout / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")
    assert text.count(old) == 1
    dockerfile.write_text(text.replace(old, new), "utf-8")
    result = _check(checkout)
    assert result.returncode == 1
    assert f"Dockerfile: {message}" in result.stderr


@pytest.mark.parametrize(
    "extra",
    [
        "RUN uv build --wheel\n",
        "RUN true && uv run nz-openbank-mcp --help\n",
        'RUN ["uv", "sync", "--frozen"]\n',
        "RUN python -m build\n",
        "RUN uvx hatch build\n",
        "RUN pip install .\n",
        "RUN <<EOF\nuv sync\nEOF\n",
    ],
)
def test_dockerfile_extra_build_step_is_caught(checkout: Path, extra: str) -> None:
    dockerfile = checkout / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")
    anchor = "COPY dist/ /tmp/dist/\n"
    assert text.count(anchor) == 1
    dockerfile.write_text(text.replace(anchor, anchor + extra), "utf-8")
    result = _check(checkout)
    assert result.returncode == 1
    assert "Dockerfile: " in result.stderr
    assert "ENV must set" not in result.stderr


def test_claude_marketplace_must_point_at_plugin(checkout: Path) -> None:
    shutil.copytree(checkout / "plugin", checkout / "other-plugin")
    _edit_json(
        checkout / ".claude-plugin/marketplace.json",
        lambda d: d["plugins"][0].update(source="./other-plugin"),
    )
    result = _check(checkout)
    assert result.returncode == 1
    assert "plugin source './other-plugin' must be the plugin/ directory" in result.stderr


def test_example_must_be_pinned(checkout: Path) -> None:
    _edit_json(
        checkout / "examples/claude_desktop_config.json",
        lambda d: d["mcpServers"]["nz-openbank"].update(args=["nz-openbank-mcp"]),
    )
    result = _check(checkout)
    assert result.returncode == 1
    assert "examples/claude_desktop_config.json: nz-openbank: launch must be uvx" in result.stderr


def test_example_must_keep_safe_values_and_placeholders(checkout: Path) -> None:
    def unsafe(d: Any) -> None:
        env = d["mcpServers"]["nz-openbank"]["env"]
        env["AKAHU_READ_ONLY"] = "false"
        env["AKAHU_USER_TOKEN"] = "user_token_real"

    _edit_json(checkout / "examples/claude_desktop_config.json", unsafe)
    result = _check(checkout)
    assert "AKAHU_READ_ONLY must be 'true'" in result.stderr
    assert "AKAHU_USER_TOKEN must be a placeholder" in result.stderr


def test_registry_missing_and_undeclared_entries_fail(checkout: Path) -> None:
    def change(d: Any) -> None:
        env = d["packages"][0]["environmentVariables"]
        env[:] = [e for e in env if e["name"] not in {"AKAHU_READ_ONLY", "AKAHU_USER_TOKEN"}]
        env.append({"name": "AKAHU_BASE_URL", "format": "string"})

    _edit_json(checkout / "server.json", change)
    result = _check(checkout)
    assert result.returncode == 1
    assert "server.json: AKAHU_READ_ONLY is a declared setting but is missing" in result.stderr
    assert "server.json: AKAHU_USER_TOKEN is a declared setting but is missing" in result.stderr
    assert "server.json: AKAHU_BASE_URL is not a declared setting" in result.stderr


def test_example_missing_and_undeclared_entries_fail(checkout: Path) -> None:
    def change(d: Any) -> None:
        env = d["mcpServers"]["nz-openbank"]["env"]
        del env["AKAHU_READ_ONLY"]
        del env["AKAHU_USER_TOKEN"]
        env["AKAHU_BASE_URL"] = "https://example.com"

    _edit_json(checkout / "examples/claude_desktop_config.json", change)
    result = _check(checkout)
    assert result.returncode == 1
    assert "AKAHU_READ_ONLY must be 'true', got None" in result.stderr
    assert "AKAHU_USER_TOKEN must be a placeholder" in result.stderr
    assert "env AKAHU_BASE_URL is not a declared setting" in result.stderr
