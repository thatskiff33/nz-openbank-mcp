"""Validate plugin, marketplace and Desktop Extension manifests.

Checks: every manifest parses as JSON with its required keys, versions match
pyproject.toml, each launch spec runs the PyPI release pinned to that version,
each launch-spec env var is injected from the user config key
of the same name (AKAHU_READ_ONLY <- akahu_read_only) and every declared key is
injected, the plugin and Desktop Extension declare the same keys, tokens are
marked sensitive, safety defaults stay read-only, and no root .mcp.json exists.
Exits non-zero on any failure.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
USER_CONFIG_REF = re.compile(r"^\$\{user_config\.([a-z0-9_]+)\}$")
SAFE_DEFAULTS = {"akahu_read_only": "true", "akahu_automation_bypass": "false"}
SENSITIVE_KEYS = {"akahu_user_token", "akahu_app_token"}

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
        if not obj(config.get(key, {}), f"{rel}: {key}").get("sensitive"):
            fail(f"{rel}: {key} must be declared sensitive")
    for key, expected in SAFE_DEFAULTS.items():
        actual = obj(config.get(key, {}), f"{rel}: {key}").get("default")
        if actual != expected:
            fail(f"{rel}: {key} default must be {expected!r}, got {actual!r}")


def main() -> int:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]

    marketplace_rel = ".claude-plugin/marketplace.json"
    marketplace = load(marketplace_rel)
    require(marketplace_rel, marketplace, "name", "owner", "plugins")
    for plugin_entry in marketplace.get("plugins", []):
        source = obj(plugin_entry, marketplace_rel).get("source")
        if not isinstance(source, str):
            fail(f"{marketplace_rel}: plugin source must be a relative path, got {source!r}")
        elif not (ROOT / source / ".claude-plugin" / "plugin.json").is_file():
            fail(f"{marketplace_rel}: plugin source {source!r} has no .claude-plugin/plugin.json")

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

    if (ROOT / ".mcp.json").exists():
        fail(".mcp.json must not exist at the repo root")

    for msg in errors:
        print(f"error: {msg}", file=sys.stderr)
    if not errors:
        print(f"packaging ok: version {version} in lockstep")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
