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
    "npm/package.json",
    "npm/bin/nz-openbank-mcp.js",
    "npm/bin/nz-openbank-mcp-http.js",
    "npm/lib/launch.js",
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
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
            "uv sync needs --no-build --no-install-project",
        ),
        (
            "uv sync --frozen --no-dev --no-install-project --no-build",
            "uv sync --frozen --no-dev --no-install-project",
            "uv sync needs --no-build",
        ),
        (
            '--no-deps --no-build "$wheel"',
            '--no-deps "$wheel"',
            "uv pip install needs --no-build",
        ),
        (
            '--no-deps --no-build "$wheel"',
            '--no-deps --no-build --build "$wheel"',
            "uv --build undoes --no-build",
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


ANCHOR = "COPY pyproject.toml uv.lock ./\n"


def _add_after_anchor(checkout: Path, extra: str) -> subprocess.CompletedProcess[str]:
    dockerfile = checkout / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")
    assert text.count(ANCHOR) == 1
    dockerfile.write_text(text.replace(ANCHOR, ANCHOR + extra), "utf-8")
    return _check(checkout)


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        # uv commands outside the allowlist, however they are spelled.
        ("RUN uv build --wheel\n", "uv build is not allowed"),
        ("RUN uv -q build\n", "uv build is not allowed"),
        ("RUN uv --cache-dir /tmp/c lock\n", "uv /tmp/c lock is not allowed"),
        ("RUN true && uv run nz-openbank-mcp --help\n", "uv run nz-openbank-mcp is not allowed"),
        ("RUN uv tool install hatch\n", "uv tool install is not allowed"),
        ("RUN uv add hatchling\n", "uv add hatchling is not allowed"),
        ("RUN uv remove httpx\n", "uv remove httpx is not allowed"),
        ("RUN uv version --bump patch\n", "uv version patch is not allowed"),
        ("RUN uv pip wheel .\n", "uv pip wheel is not allowed"),
        ("RUN uv pip compile pyproject.toml\n", "uv pip compile is not allowed"),
        ("RUN uv pip sync /tmp/req.txt\n", "uv pip sync is not allowed"),
        ("RUN uv --no-cache sync --frozen\n", "uv sync needs --no-build --no-install-project"),
        ('RUN ["uv", "sync", "--frozen"]\n', "uv sync needs --no-build --no-install-project"),
        ("RUN x=$(uv build)\n", "uv build is not allowed"),
        ("RUN true & uv build\n", "uv build is not allowed"),
        ("ONBUILD RUN uv build\n", "uv build is not allowed"),
        ("RUN echo hi \\\n# a comment\n    && uv build\n", "uv build is not allowed"),
        ("RUN echo hi \\\n\n    && uv build\n", "uv build is not allowed"),
        # Programs and wrappers outside the allowlist.
        ("RUN uvx hatch build\n", "RUN uses uvx, which this check does not allow"),
        ("RUN hatch build\n", "RUN uses hatch, which this check does not allow"),
        ("RUN pyproject-build\n", "RUN uses pyproject-build, which"),
        ("RUN pip install --no-build .\n", "RUN uses pip, which"),
        ("RUN pip3 install .\n", "RUN uses pip3, which"),
        ("RUN pipx run build\n", "RUN uses pipx, which"),
        ("RUN sudo uv build\n", "RUN uses sudo, which"),
        ("RUN /usr/bin/env uv build\n", "RUN uses /usr/bin/env, which"),
        ("RUN timeout 600 uv build\n", "RUN uses timeout, which"),
        ("RUN ls | xargs uv build\n", "RUN uses ls, which"),
        ('RUN sh -c "uv sync"\n', "RUN uses sh, which"),
        ("RUN bash -lc 'uv build'\n", "RUN uses bash, which"),
        ('RUN ["/bin/sh", "-c", "uv build"]\n', "RUN uses /bin/sh, which"),
        # python may only run inline code.
        ("RUN python -m build\n", "python may only run -c code"),
        ("RUN python3 -mpip install .\n", "python may only run -c code"),
        ("RUN python -m hatchling build\n", "python may only run -c code"),
        ("RUN python setup.py bdist_wheel\n", "python may only run -c code"),
        # Constructs the check cannot read.
        ("RUN <<EOF\nuv sync\nEOF\n", "RUN may not use <<"),
        ("RUN bash <<EOF\nuv build\nEOF\n", "RUN may not use <<"),
        ('RUN echo "$(python -m build /ctx)"\n', "RUN may not use $( or ` inside quotes"),
        ('RUN echo "`pip install /ctx`"\n', "RUN may not use $( or ` inside quotes"),
        # Ways to change what an allowed command runs.
        ('SHELL ["pip", "install", "/ctx"]\nRUN echo\n', "SHELL changes what RUN executes"),
        ("ENV PATH=/ctx/bin:$PATH\nRUN uv pip check\n", "RUN after ENV PATH in the same stage"),
        (
            "RUN PATH=/ctx/bin uv sync --frozen --no-install-project --no-build\n",
            "RUN may not set PATH",
        ),
    ],
)
def test_dockerfile_extra_build_step_is_caught(checkout: Path, extra: str, message: str) -> None:
    result = _add_after_anchor(checkout, extra)
    assert result.returncode == 1
    assert f"Dockerfile: {message}" in result.stderr


@pytest.mark.parametrize(
    "extra",
    [
        "RUN useradd -m build app\n",
        'RUN echo "see uvx docs and pip install notes"\n',
        'RUN echo "x; pip install it first (later)" >&2\n',
        "RUN uv --version && uv pip check\n",
        "RUN uv pip list --python /app/.venv/bin/python\n",
        "RUN set -eu; if [ -n x ]; then echo ok; fi\n",
        'RUN msg="a b"; echo "$msg"\n',
        "RUN [ -f /app/pyproject.toml ] || exit 1\n",
        "RUN echo x 2>/dev/null\n",
        "RUN 2>/dev/null echo x\n",
    ],
)
def test_dockerfile_harmless_run_is_not_flagged(checkout: Path, extra: str) -> None:
    result = _add_after_anchor(checkout, extra)
    assert result.returncode == 0, result.stderr


def test_dockerfile_escape_directive_is_refused(checkout: Path) -> None:
    dockerfile = checkout / "Dockerfile"
    dockerfile.write_text("# escape=`\n" + dockerfile.read_text(encoding="utf-8"), "utf-8")
    result = _check(checkout)
    assert result.returncode == 1
    assert "Dockerfile: the escape directive is not supported" in result.stderr


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


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda d: d.update(dependencies={"left-pad": "1.3.0"}),
            "'dependencies' is not allowed",
        ),
        (lambda d: d.update(scripts={"postinstall": "node x.js"}), "'scripts' is not allowed"),
        (
            lambda d: d.update(publishConfig={"provenance": False}),
            "'publishConfig' is not allowed",
        ),
        (lambda d: d.update(version="9.9.9"), "version must be '0."),
        (lambda d: d.update(mcpName="io.github.someone/else"), "mcpName must be"),
        (lambda d: d["bin"].update(extra="bin/extra.js"), "bin must be"),
        (lambda d: d["files"].append("test/"), "files must be"),
        (
            lambda d: d["repository"].update(url="git+https://github.com/x/y.git"),
            "repository.url must be",
        ),
    ],
)
def test_npm_package_must_stay_a_bare_launcher(
    checkout: Path, change: Callable[[Any], None], message: str
) -> None:
    _edit_json(checkout / "npm/package.json", change)
    result = _check(checkout)
    assert result.returncode == 1
    assert f"npm/package.json: {message}" in result.stderr


@pytest.mark.parametrize("name", [".npmrc", "package-lock.json", ".npmignore"])
def test_npm_config_and_lock_files_are_refused(checkout: Path, name: str) -> None:
    (checkout / "npm" / name).write_text("{}", encoding="utf-8")
    result = _check(checkout)
    assert result.returncode == 1
    assert f"npm/{name} must not exist" in result.stderr


@pytest.mark.parametrize(
    ("rel", "old", "new", "message"),
    [
        (
            "npm/lib/launch.js",
            "{ stdio: 'inherit', windowsHide: true }",
            "{ stdio: 'inherit', windowsHide: true, ...{ shell: true } }",
            "must not start uvx through a shell",
        ),
        (
            "npm/lib/launch.js",
            "spawn(uvx, uvxArgs(entry, args),",
            "spawn('uvx', uvxArgs(entry, args),",
            "must contain 'spawn(uvx, uvxArgs(entry, args),'",
        ),
        (
            "npm/bin/nz-openbank-mcp-http.js",
            ".run('nz-openbank-mcp-http')",
            ".run('nz-openbank-mcp')",
            "must call require('../lib/launch.js').run('nz-openbank-mcp-http')",
        ),
    ],
)
def test_npm_launcher_must_run_the_pinned_release(
    checkout: Path, rel: str, old: str, new: str, message: str
) -> None:
    path = checkout / rel
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1
    path.write_text(text.replace(old, new), encoding="utf-8")
    result = _check(checkout)
    assert result.returncode == 1
    assert message in result.stderr


def test_registry_must_list_pypi_and_npm_at_the_release_version(checkout: Path) -> None:
    def change(d: Any) -> None:
        d["packages"][1].update(version="0.0.1", runtimeHint="node")
        d["packages"].append(dict(d["packages"][0], registryType="oci"))

    _edit_json(checkout / "server.json", change)
    result = _check(checkout)
    assert result.returncode == 1
    assert "server.json: packages must be one each of ['npm', 'pypi']" in result.stderr
    assert "server.json: npm package must be nz-openbank-mcp 0." in result.stderr
    assert "npm package must use https://registry.npmjs.org with runtimeHint 'npx'" in (
        result.stderr
    )


def test_root_npmrc_is_refused(checkout: Path) -> None:
    (checkout / ".npmrc").write_text("registry=https://example.invalid/", encoding="utf-8")
    result = _check(checkout)
    assert result.returncode == 1
    assert ".npmrc must not exist at the repo root" in result.stderr


def test_ci_dry_run_must_use_the_release_node_pin(checkout: Path) -> None:
    path = checkout / ".github/workflows/release.yml"
    text = path.read_text(encoding="utf-8")
    assert text.count('NPM_NODE_VERSION: "') == 1
    path.write_text(text.replace('NPM_NODE_VERSION: "', 'NPM_NODE_VERSION: "1'), encoding="utf-8")
    result = _check(checkout)
    assert result.returncode == 1
    assert "the npm publish dry run must use Node 1" in result.stderr


def test_release_node_pin_must_be_exact(checkout: Path) -> None:
    path = checkout / ".github/workflows/release.yml"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace('NPM_NODE_VERSION: "24.16.0"', 'NPM_NODE_VERSION: "lts/*"'), encoding="utf-8"
    )
    result = _check(checkout)
    assert result.returncode == 1
    assert "NPM_NODE_VERSION must pin an exact Node version" in result.stderr
