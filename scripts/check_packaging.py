"""Validate plugin, marketplace and Desktop Extension manifests.

Checks: every manifest parses as JSON with its required keys, versions match
pyproject.toml, each launch spec runs the PyPI release pinned to that version,
each Claude Code and Desktop Extension env var is injected from the user config
key of the same name (AKAHU_READ_ONLY <- akahu_read_only) and every declared key
is injected, the plugin and Desktop Extension declare the same keys, tokens are
marked sensitive, and safety defaults stay read-only. For Codex, Cursor and
Grok: env values are placeholders only (no literal values), Codex forwards
exactly the declared variables, Cursor and Grok carry the same safe inline
defaults, and every marketplace index points at plugin/. server.json lists the
PyPI and npm packages at the pinned version, marks the tokens secret with no
default and carries the pinned defaults. The npm launcher (npm/) has the same
version, no dependencies, scripts or publish settings, exactly its two bins and
file list, and starts the pinned PyPI release with uvx and no shell. No sensitive key
has a default anywhere; the Dockerfile keeps the safe AKAHU_* defaults and its
RUN commands use only allowlisted programs and uv commands; and
examples/claude_desktop_config.json runs the pinned release with safe values.
No root .mcp.json or portable plugin/plugin.json may exist. Exits non-zero on
any failure. `--root DIR` checks another checkout (used by the tests).
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
USER_CONFIG_REF = re.compile(r"^\$\{user_config\.([a-z0-9_]+)\}$")
# Defaults every host must ship.
PINNED_DEFAULTS = {
    "akahu_read_only": "true",
    "akahu_automation_bypass": "false",
    "akahu_mask_accounts": "false",
}
SENSITIVE_KEYS = {"akahu_user_token", "akahu_app_token"}
# Dockerfile RUN commands are checked against an allowlist, so anything that
# could build the package (a new tool, or a wrapper such as sudo or xargs) fails
# until it is added here deliberately. uv and python have their own rules.
RUN_PROGRAMS = {"set", "echo", "printf", "exit", "test", "[", "true", "false", "useradd"}
SHELL_KEYWORDS = {"if", "then", "else", "elif", "fi", "!"}
# uv commands the image build may run, with the flags each one must carry.
UV_ALLOWED = {
    ("sync",): {"--frozen", "--no-install-project", "--no-build"},
    ("pip", "install"): {"--no-deps", "--no-build"},
    ("pip", "check"): set(),
    ("pip", "list"): set(),
}

PACKAGE = "nz-openbank-mcp"
# The npm launcher: one bin per console script, and only these in the tarball
# (npm adds package.json, README.md and LICENSE itself).
NPM_BINS = {
    "nz-openbank-mcp": "bin/nz-openbank-mcp.js",
    "nz-openbank-mcp-http": "bin/nz-openbank-mcp-http.js",
}
NPM_FILES = ["bin/", "lib/", "NOTICE"]
NPM_REPOSITORY = "git+https://github.com/thatskiff33/nz-openbank-mcp.git"
# Anything that would make installing or publishing the launcher fetch or run
# other code, or send it somewhere else.
NPM_FORBIDDEN_KEYS = {
    "dependencies",
    "devDependencies",
    "optionalDependencies",
    "peerDependencies",
    "bundleDependencies",
    "bundledDependencies",
    "overrides",
    "workspaces",
    "scripts",
    "gypfile",
    "publishConfig",
}
NPM_FORBIDDEN_FILES = (
    ".npmrc",
    ".npmignore",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "binding.gyp",
)
# server.json install routes: registry type -> (registry, runtime hint).
REGISTRY_PACKAGES = {
    "pypi": ("https://pypi.org", "uvx"),
    "npm": ("https://registry.npmjs.org", "npx"),
}

errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def obj(value: Any, where: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    fail(f"{where}: expected an object, got {type(value).__name__}")
    return {}


def load(rel: str) -> dict[str, Any]:
    try:
        data = json.loads((ROOT / rel).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"{rel}: {exc}")
        return {}
    return obj(data, rel)


def require(rel: str, data: dict[str, Any], *keys: str) -> None:
    for key in keys:
        if key not in data:
            fail(f"{rel}: missing required key {key!r}")


def check_env(rel: str, env: dict[str, Any], declared: dict[str, Any]) -> None:
    injected: set[str] = set()
    for var, value in env.items():
        match = USER_CONFIG_REF.match(value) if isinstance(value, str) else None
        if not match:
            fail(f"{rel}: env {var} must be a ${{user_config.KEY}} reference, got {value!r}")
            continue
        key = match.group(1)
        injected.add(key)
        if key not in declared:
            fail(f"{rel}: env {var} references undeclared user config {key!r}")
        if var.lower() != key:
            fail(f"{rel}: env {var} must be injected from user config {var.lower()!r}, not {key!r}")
    for key in sorted(set(declared) - injected):
        fail(f"{rel}: user config {key!r} is declared but never injected into env")


def check_launch(rel: str, server: dict[str, Any], version: str) -> None:
    expected = ["--from", f"nz-openbank-mcp=={version}", "nz-openbank-mcp"]
    if server.get("command") != "uvx" or server.get("args") != expected:
        fail(
            f"{rel}: launch must be uvx {' '.join(expected)}, got "
            f"{server.get('command')!r} {server.get('args')!r}"
        )


def check_user_config(rel: str, config: dict[str, Any]) -> None:
    for key in sorted(SENSITIVE_KEYS):
        entry = obj(config.get(key, {}), f"{rel}: {key}")
        if not entry.get("sensitive"):
            fail(f"{rel}: {key} must be declared sensitive")
        if "default" in entry:
            fail(f"{rel}: {key} is sensitive and must not have a default")
    for key, expected in PINNED_DEFAULTS.items():
        actual = obj(config.get(key, {}), f"{rel}: {key}").get("default")
        if actual != expected:
            fail(f"{rel}: {key} default must be {expected!r}, got {actual!r}")


def servers(rel: str, data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    found = obj(data.get("mcpServers", {}), f"{rel}: mcpServers")
    if not found:
        fail(f"{rel}: no MCP servers declared")
    return {name: obj(server, f"{rel}: {name}") for name, server in found.items()}


def check_inline_default_env(rel: str, env: dict[str, Any], keys: set[str]) -> None:
    expected = {key.upper(): PINNED_DEFAULTS.get(key, "") for key in keys}
    for var, default in expected.items():
        want = f"${{{var}:-{default}}}"
        if env.get(var) != want:
            fail(f"{rel}: env {var} must be {want!r}, got {env.get(var)!r}")
    for var in sorted(set(env) - set(expected)):
        fail(f"{rel}: env {var} is not a declared setting")


def check_registry(version: str, keys: set[str]) -> None:
    rel = "server.json"
    packages = [obj(raw, rel) for raw in load(rel).get("packages", [])]
    kinds = [package.get("registryType") for package in packages]
    if sorted(map(str, kinds)) != sorted(REGISTRY_PACKAGES):
        fail(f"{rel}: packages must be one each of {sorted(REGISTRY_PACKAGES)}, got {kinds}")
    for package in packages:
        kind = str(package.get("registryType"))
        where = f"{rel}: {kind} package"
        if package.get("identifier") != PACKAGE or package.get("version") != version:
            fail(f"{where} must be {PACKAGE} {version}")
        if kind in REGISTRY_PACKAGES:
            registry, hint = REGISTRY_PACKAGES[kind]
            if package.get("registryBaseUrl") != registry or package.get("runtimeHint") != hint:
                fail(f"{where} must use {registry} with runtimeHint {hint!r}")
    for package in packages:
        entries = [obj(raw, rel) for raw in package.get("environmentVariables", [])]
        names = {str(entry.get("name", "")).lower() for entry in entries}
        for key in sorted(keys - names):
            fail(f"{rel}: {key.upper()} is a declared setting but is missing")
        for key in sorted(names - keys):
            fail(f"{rel}: {key.upper()} is not a declared setting")
        for entry in entries:
            key = str(entry.get("name", "")).lower()
            if key in SENSITIVE_KEYS:
                if not entry.get("isSecret"):
                    fail(f"{rel}: {entry.get('name')} must be isSecret")
                if "default" in entry:
                    fail(f"{rel}: {entry.get('name')} is secret and must not have a default")
            if key in PINNED_DEFAULTS and entry.get("default") != PINNED_DEFAULTS[key]:
                fail(
                    f"{rel}: {entry.get('name')} default must be {PINNED_DEFAULTS[key]!r}, "
                    f"got {entry.get('default')!r}"
                )


def check_dockerfile() -> None:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    # Only the final stage reaches the image, and its last assignment wins.
    final_stage = re.split(r"(?mi)^\s*FROM\s", text)[-1]
    for var, value in (("AKAHU_READ_ONLY", "true"), ("AKAHU_AUTOMATION_BYPASS", "false")):
        values = re.findall(rf"\b{var}=(\S+)", final_stage)
        if not values or values[-1].rstrip("\\") != value:
            fail(f"Dockerfile: ENV must set {var}={value} in the final stage")
    # The image installs a wheel built with the hash-pinned backend, so RUN may
    # only use allowlisted commands. CI's image job also fails if the build log
    # shows any build.
    if re.search(r"(?im)^\s*#\s*escape\s*=", text):
        fail("Dockerfile: the escape directive is not supported by this check")
    path_changed = False
    for instruction in dockerfile_instructions(text):
        keyword = instruction.split(maxsplit=1)[0].upper()
        if keyword == "FROM":
            path_changed = False
        elif keyword == "SHELL":
            fail("Dockerfile: SHELL changes what RUN executes and is not supported")
        elif keyword == "ENV" and re.search(r"\bPATH=", instruction):
            path_changed = True
        match = re.match(r"(?i)(?:ONBUILD\s+)?RUN\b(.*)", instruction, re.DOTALL)
        if match:
            if path_changed:
                fail("Dockerfile: RUN after ENV PATH in the same stage is not checked")
            check_run(match.group(1))


def dockerfile_instructions(text: str) -> list[str]:
    """Instructions as Docker reads them: comment and blank lines inside a
    continuation are dropped, and backslash continuations are joined."""
    instructions: list[str] = []
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        current += " " + line
        if current.endswith("\\"):
            current = current[:-1]
        else:
            instructions.append(current.strip())
            current = ""
    if current.strip():
        instructions.append(current.strip())
    return instructions


def check_run(body: str) -> None:
    body = re.sub(r"^\s*(--\S+\s+)*", "", body)  # RUN --mount=... and similar flags
    # Exec form is a JSON list of strings; anything else is shell form, as in Docker.
    try:
        exec_form = json.loads(body) if body.startswith("[") else None
    except json.JSONDecodeError:
        exec_form = None
    if isinstance(exec_form, list) and all(isinstance(w, str) for w in exec_form):
        check_command(exec_form)
        return
    if "<<" in body:
        fail(f"Dockerfile: RUN may not use << (heredocs are not checked): {body}")
        return
    # Drop redirections and their targets (>&2, 2>/dev/null) so their & and
    # file names do not read as operators or programs.
    body = re.sub(r"[0-9]*[<>]+(&[0-9]+|\s*[^\s;&|()]+)", " ", body)
    lexer = shlex.shlex(body, posix=True, punctuation_chars=";&|()`")
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        fail(f"Dockerfile: RUN could not be parsed: {body}")
        return
    words: list[str] = []
    for token in [*tokens, ";"]:
        # A run of operator characters (;, &&, |, $( and so on) ends a command.
        if token and all(ch in ";&|()`" for ch in token):
            check_command(words)
            words = []
        elif "$(" in token or "`" in token:
            # Inside double quotes shlex keeps a substitution as one word, but
            # the shell still runs it.
            fail(f"Dockerfile: RUN may not use $( or ` inside quotes: {token}")
        else:
            words.append(token)


def check_command(words: list[str]) -> None:
    while words and (words[0] in SHELL_KEYWORDS or re.fullmatch(r"\w+=.*", words[0], re.DOTALL)):
        if words[0].startswith("PATH="):
            fail(f"Dockerfile: RUN may not set PATH: {' '.join(words)}")
        words = words[1:]
    if not words:
        return
    shown = " ".join(words)
    program, args = words[0], words[1:]
    if program == "uv":
        if args == ["--version"]:
            return
        if "--build" in args:
            fail(f"Dockerfile: uv --build undoes --no-build: {shown}")
            return
        positional = tuple(a for a in args if not a.startswith("-"))
        command = next((c for c in UV_ALLOWED if positional[: len(c)] == c), None)
        if command is None:
            fail(f"Dockerfile: uv {' '.join(positional[:2])} is not allowed in RUN: {shown}")
        elif missing := sorted(UV_ALLOWED[command] - set(args)):
            fail(f"Dockerfile: uv {' '.join(command)} needs {' '.join(missing)}: {shown}")
    elif program in {"python", "python3"}:
        # Only inline code; -m, scripts and setup.py could start a build.
        if args[:1] != ["-c"]:
            fail(f"Dockerfile: python may only run -c code in RUN: {shown}")
    elif program not in RUN_PROGRAMS:
        fail(f"Dockerfile: RUN uses {program}, which this check does not allow: {shown}")


def check_example(version: str, keys: set[str]) -> None:
    rel = "examples/claude_desktop_config.json"
    for name, server in servers(rel, load(rel)).items():
        check_launch(f"{rel}: {name}", server, version)
        env = obj(server.get("env", {}), f"{rel}: {name}.env")
        for var in sorted(set(env) - {key.upper() for key in keys}):
            fail(f"{rel}: env {var} is not a declared setting")
        for key, expected in PINNED_DEFAULTS.items():
            if env.get(key.upper()) != expected:
                fail(f"{rel}: {key.upper()} must be {expected!r}, got {env.get(key.upper())!r}")
        for key in sorted(SENSITIVE_KEYS):
            if "REPLACE" not in str(env.get(key.upper(), "")):
                fail(f"{rel}: {key.upper()} must be a placeholder")


def check_other_hosts(version: str, keys: set[str]) -> None:
    variables = {key.upper() for key in keys}

    for rel in (
        "plugin/.codex-plugin/plugin.json",
        "plugin/.cursor-plugin/plugin.json",
        "plugin/.grok-plugin/plugin.json",
    ):
        manifest = load(rel)
        require(rel, manifest, "name", "version", "description", "mcpServers")
        if manifest.get("version") != version:
            fail(f"{rel}: version {manifest.get('version')!r} != pyproject.toml {version!r}")

    codex_rel = "plugin/codex-mcp.json"
    if load("plugin/.codex-plugin/plugin.json").get("mcpServers") != "./codex-mcp.json":
        fail("plugin/.codex-plugin/plugin.json: mcpServers must be './codex-mcp.json'")
    for name, server in servers(codex_rel, load(codex_rel)).items():
        check_launch(f"{codex_rel}: {name}", server, version)
        if "env" in server:
            fail(f"{codex_rel}: {name} must not set env; settings come from env_vars only")
        if sorted(server.get("env_vars", [])) != sorted(variables):
            fail(f"{codex_rel}: {name} env_vars must be exactly {sorted(variables)}")

    cursor_rel = "plugin/.cursor-plugin/plugin.json"
    cursor = load(cursor_rel)
    cursor_variables = obj(cursor.get("variables", {}), cursor_rel)
    declared = set(obj(cursor_variables.get("properties", {}), cursor_rel))
    if declared != variables:
        fail(f"{cursor_rel}: variables must declare exactly {sorted(variables)}")
    for name, server in servers(cursor_rel, cursor).items():
        check_launch(f"{cursor_rel}: {name}", server, version)
        check_inline_default_env(cursor_rel, obj(server.get("env", {}), cursor_rel), keys)

    grok_rel = "plugin/grok-mcp.json"
    if load("plugin/.grok-plugin/plugin.json").get("mcpServers") != "./grok-mcp.json":
        fail("plugin/.grok-plugin/plugin.json: mcpServers must be './grok-mcp.json'")
    for name, server in servers(grok_rel, load(grok_rel)).items():
        check_launch(f"{grok_rel}: {name}", server, version)
        check_inline_default_env(grok_rel, obj(server.get("env", {}), grok_rel), keys)

    for rel, key in (
        (".agents/plugins/marketplace.json", "path"),
        (".cursor-plugin/marketplace.json", None),
        (".grok-plugin/marketplace.json", "path"),
    ):
        marketplace = load(rel)
        require(rel, marketplace, "name", "plugins")
        for entry in marketplace.get("plugins", []):
            source = obj(entry, rel).get("source")
            path = obj(source, rel).get(key) if key else source
            if path not in ("plugin", "./plugin"):
                fail(f"{rel}: plugin source {path!r} must be the plugin/ directory")


def check_npm(version: str) -> None:
    """npm/: a launcher with no dependencies or scripts that runs the PyPI release."""
    rel = "npm/package.json"
    package = load(rel)
    expected: dict[str, Any] = {
        "name": PACKAGE,
        "version": version,
        "mcpName": load("server.json").get("name"),
        "bin": NPM_BINS,
        "files": NPM_FILES,
    }
    for key, want in expected.items():
        if package.get(key) != want:
            fail(f"{rel}: {key} must be {want!r}, got {package.get(key)!r}")
    repository = obj(package.get("repository", {}), f"{rel}: repository")
    if repository.get("url") != NPM_REPOSITORY:
        fail(f"{rel}: repository.url must be {NPM_REPOSITORY!r} (npm provenance checks it)")
    for key in sorted(NPM_FORBIDDEN_KEYS & set(package)):
        fail(f"{rel}: {key!r} is not allowed; the launcher installs and runs nothing else")
    for name in NPM_FORBIDDEN_FILES:
        if (ROOT / "npm" / name).exists():
            fail(f"npm/{name} must not exist")
    for entry, script in NPM_BINS.items():
        path = ROOT / "npm" / script
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        if f"require('../lib/launch.js').run('{entry}');" not in text:
            fail(f"npm/{script}: must call require('../lib/launch.js').run('{entry}')")
    launcher = ROOT / "npm" / "lib" / "launch.js"
    source = launcher.read_text(encoding="utf-8") if launcher.is_file() else ""
    for needle in ("spawn('uvx', uvxArgs(", "'--from', `${PACKAGE}==${version}`"):
        if needle not in source:
            fail(f"npm/lib/launch.js: must contain {needle!r}")
    if "shell:" in "".join(source.split()):
        fail("npm/lib/launch.js: must not start uvx through a shell")


def check_claude_marketplace() -> None:
    rel = ".claude-plugin/marketplace.json"
    marketplace = load(rel)
    require(rel, marketplace, "name", "owner", "plugins")
    for plugin_entry in marketplace.get("plugins", []):
        source = obj(plugin_entry, rel).get("source")
        if not isinstance(source, str):
            fail(f"{rel}: plugin source must be a relative path, got {source!r}")
        elif source not in ("plugin", "./plugin"):
            fail(f"{rel}: plugin source {source!r} must be the plugin/ directory")
        elif not (ROOT / source / ".claude-plugin" / "plugin.json").is_file():
            fail(f"{rel}: plugin source {source!r} has no .claude-plugin/plugin.json")


def main(argv: list[str] | None = None) -> int:
    global ROOT  # noqa: PLW0603 - one checkout per run; --root swaps it for tests
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="checkout to check")
    ROOT = parser.parse_args(argv).root.resolve()

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]

    check_claude_marketplace()

    plugin_rel = "plugin/.claude-plugin/plugin.json"
    plugin = load(plugin_rel)
    require(plugin_rel, plugin, "name", "version", "description", "userConfig")
    user_config = obj(plugin.get("userConfig", {}), f"{plugin_rel}: userConfig")
    check_user_config(plugin_rel, user_config)

    mcp_rel = "plugin/.mcp.json"
    mcp = load(mcp_rel)
    require(mcp_rel, mcp, "mcpServers")
    for name, server in obj(mcp.get("mcpServers", {}), f"{mcp_rel}: mcpServers").items():
        server_obj = obj(server, f"{mcp_rel}: {name}")
        check_launch(f"{mcp_rel}: {name}", server_obj, version)
        check_env(mcp_rel, obj(server_obj.get("env", {}), f"{mcp_rel}: {name}.env"), user_config)

    mcpb_rel = "mcpb/manifest.json"
    mcpb = load(mcpb_rel)
    require(mcpb_rel, mcpb, "manifest_version", "name", "version", "server", "user_config")
    mcpb_config = obj(mcpb.get("user_config", {}), f"{mcpb_rel}: user_config")
    check_user_config(mcpb_rel, mcpb_config)
    mcp_config = obj(obj(mcpb.get("server", {}), mcpb_rel).get("mcp_config", {}), mcpb_rel)
    check_launch(mcpb_rel, mcp_config, version)
    check_env(mcpb_rel, obj(mcp_config.get("env", {}), f"{mcpb_rel}: env"), mcpb_config)

    if set(user_config) != set(mcpb_config):
        fail(
            f"{plugin_rel} userConfig and {mcpb_rel} user_config declare different keys: "
            f"{sorted(set(user_config) ^ set(mcpb_config))}"
        )

    for rel, data in ((plugin_rel, plugin), (mcpb_rel, mcpb)):
        if data.get("version") != version:
            fail(f"{rel}: version {data.get('version')!r} != pyproject.toml {version!r}")

    check_other_hosts(version, set(user_config))
    check_registry(version, set(user_config))
    check_npm(version)
    check_dockerfile()
    check_example(version, set(user_config))

    init = (ROOT / "src" / "nz_openbank_mcp" / "__init__.py").read_text(encoding="utf-8")
    if f'__version__ = "{version}"' not in init:
        fail(f"src/nz_openbank_mcp/__init__.py: __version__ != pyproject.toml {version!r}")

    if (ROOT / ".mcp.json").exists():
        fail(".mcp.json must not exist at the repo root")
    for rel in ("plugin/plugin.json", "plugin/mcp.json"):
        if (ROOT / rel).exists():
            fail(f"{rel} must not exist; hosts would load it ahead of the per-host manifests")

    for msg in errors:
        print(f"error: {msg}", file=sys.stderr)
    if not errors:
        print(f"packaging ok: version {version} in lockstep")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
