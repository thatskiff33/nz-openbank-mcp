"""Generate every host plugin manifest from plugin/plugin.base.toml.

Writes the Claude Code, Codex, Cursor and Grok Build plugin manifests, their
MCP launch specs, each host's repo marketplace index, and the Desktop Extension
manifest. The version comes from pyproject.toml, so a version bump is one edit
plus a re-run. `--check` exits non-zero if any committed file differs from what
would be generated.

Each host passes credentials differently, and none of them lets a committed
file hold a secret:

- Claude Code and the Desktop Extension prompt at install and substitute
  `${user_config.KEY}` from the OS keychain.
- Codex forwards the variables named in `env_vars` from the environment Codex
  was started in. Unset optional settings fall back to the server's defaults.
- Cursor substitutes `${VAR}` from plugin variables set under Plugins ->
  Configure, falling back to its own environment. It ignores schema defaults
  and passes an unset `${VAR}` through literally, so defaults are inline.
- Grok expands `${VAR}` from the environment Grok was started in.

Cursor and Grok both accept `${VAR:-default}`; tokens default to empty so an
unset token reads as missing rather than as placeholder text.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "plugin" / "plugin.base.toml"
PLUGIN_DIR = "plugin"
CODEX_MCP = "codex-mcp.json"
# Grok ignores inline mcpServers in its manifest; it needs a path.
GROK_MCP = "grok-mcp.json"


def load_base() -> dict[str, Any]:
    base = tomllib.loads(BASE.read_text(encoding="utf-8"))
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    base["version"] = pyproject["project"]["version"]
    for setting in base["setting"]:
        if setting["key"] != setting["var"].lower():
            raise SystemExit(f"plugin.base.toml: key {setting['key']!r} must be {setting['var'].lower()!r}")
        if not setting.get("sensitive") and "default" not in setting:
            raise SystemExit(f"plugin.base.toml: {setting['var']} needs a default or sensitive = true")
    return base


def launch(base: dict[str, Any]) -> dict[str, Any]:
    package = f"{base['name']}=={base['version']}"
    return {"command": "uvx", "args": ["--from", package, base["name"]]}


def author(base: dict[str, Any], *, url: bool) -> dict[str, str]:
    data = {"name": base["author"]["name"], "email": base["author"]["email"]}
    if url:
        data["url"] = base["author"]["url"]
    return data


def user_config(base: dict[str, Any], *, required: bool) -> dict[str, Any]:
    config: dict[str, Any] = {}
    for setting in base["setting"]:
        entry: dict[str, Any] = {
            "type": "string",
            "title": setting["title"],
            "description": setting["description"],
        }
        if setting.get("sensitive"):
            entry["sensitive"] = True
        if "default" in setting:
            entry["default"] = setting["default"]
        if required:
            entry["required"] = bool(setting.get("sensitive"))
        config[setting["key"]] = entry
    return config


def user_config_env(base: dict[str, Any]) -> dict[str, str]:
    return {s["var"]: f"${{user_config.{s['key']}}}" for s in base["setting"]}


def claude_plugin(base: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": base["name"],
        "version": base["version"],
        "description": base["description"],
        "author": author(base, url=True),
        "homepage": base["homepage"],
        "repository": base["repository"],
        "license": base["license"],
        "keywords": base["keywords"],
        "userConfig": user_config(base, required=False),
    }


def claude_mcp(base: dict[str, Any]) -> dict[str, Any]:
    return {"mcpServers": {base["server_name"]: {**launch(base), "env": user_config_env(base)}}}


def claude_marketplace(base: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": base["marketplace"]["name"],
        "owner": {"name": base["author"]["name"]},
        "description": base["marketplace"]["description"],
        "plugins": [
            {
                "name": base["name"],
                "source": f"./{PLUGIN_DIR}",
                "description": base["marketplace"]["description"],
            }
        ],
    }


def codex_plugin(base: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": base["name"],
        "version": base["version"],
        "description": base["description"],
        "author": author(base, url=True),
        "homepage": base["homepage"],
        "repository": base["repository"],
        "license": base["license"],
        "keywords": base["keywords"],
        "mcpServers": f"./{CODEX_MCP}",
        "interface": {
            "displayName": base["display_name"],
            "shortDescription": base["short_description"],
            "longDescription": base["description"],
            "developerName": base["author"]["name"],
            "category": base["category"],
            "capabilities": ["Read", "Write"],
            "websiteURL": base["homepage"],
        },
    }


def codex_mcp(base: dict[str, Any]) -> dict[str, Any]:
    env_vars = [s["var"] for s in base["setting"]]
    return {"mcpServers": {base["server_name"]: {**launch(base), "env_vars": env_vars}}}


def codex_marketplace(base: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": base["marketplace"]["name"],
        "interface": {"displayName": base["marketplace"]["display_name"]},
        "plugins": [
            {
                "name": base["name"],
                "source": {"source": "local", "path": f"./{PLUGIN_DIR}"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": base["category"],
            }
        ],
    }


def cursor_plugin(base: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for setting in base["setting"]:
        prop: dict[str, Any] = {
            "type": "string",
            "title": setting["title"],
            "description": setting["description"],
        }
        if "default" in setting:
            prop["default"] = setting["default"]
        properties[setting["var"]] = prop
    return {
        "name": base["name"],
        "version": base["version"],
        "description": base["description"],
        "author": author(base, url=False),
        "homepage": base["homepage"],
        "repository": base["repository"],
        "license": base["license"],
        "keywords": base["keywords"],
        "category": base["category"].lower(),
        "variables": {
            "type": "object",
            "properties": properties,
            "required": [s["var"] for s in base["setting"] if s.get("sensitive")],
        },
        "mcpServers": {base["server_name"]: {**launch(base), "env": inline_default_env(base)}},
    }


def cursor_marketplace(base: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": base["marketplace"]["name"],
        "owner": {"name": base["author"]["name"], "email": base["author"]["email"]},
        "metadata": {"description": base["marketplace"]["description"]},
        "plugins": [
            {
                "name": base["name"],
                "source": PLUGIN_DIR,
                "description": base["marketplace"]["description"],
            }
        ],
    }


def inline_default_env(base: dict[str, Any]) -> dict[str, str]:
    return {s["var"]: f"${{{s['var']}:-{s.get('default', '')}}}" for s in base["setting"]}


def grok_plugin(base: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": base["name"],
        "version": base["version"],
        "description": base["description"],
        "author": author(base, url=True),
        "homepage": base["homepage"],
        "repository": base["repository"],
        "license": base["license"],
        "keywords": base["keywords"],
        "mcpServers": f"./{GROK_MCP}",
    }


def grok_mcp(base: dict[str, Any]) -> dict[str, Any]:
    return {"mcpServers": {base["server_name"]: {**launch(base), "env": inline_default_env(base)}}}


def grok_marketplace(base: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": base["marketplace"]["name"],
        "description": base["marketplace"]["description"],
        "owner": {"name": base["author"]["name"], "email": base["author"]["email"]},
        "plugins": [
            {
                "name": base["name"],
                "description": base["description"],
                "version": base["version"],
                "category": base["category"].lower(),
                "source": {"type": "local", "path": f"./{PLUGIN_DIR}"},
            }
        ],
    }


def mcpb_manifest(base: dict[str, Any]) -> dict[str, Any]:
    return {
        "manifest_version": "0.3",
        "name": base["name"],
        "display_name": base["display_name"],
        "version": base["version"],
        "description": base["description"],
        "author": author(base, url=True),
        "homepage": base["homepage"],
        "repository": {"type": "git", "url": base["repository"]},
        "license": base["license"],
        "keywords": base["keywords"],
        "server": {
            "type": "python",
            "entry_point": "nz_openbank_mcp.server",
            "mcp_config": {**launch(base), "env": user_config_env(base)},
        },
        "user_config": user_config(base, required=True),
        "compatibility": {"platforms": ["darwin", "win32", "linux"]},
    }


def render(base: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        ".claude-plugin/marketplace.json": claude_marketplace(base),
        ".agents/plugins/marketplace.json": codex_marketplace(base),
        ".cursor-plugin/marketplace.json": cursor_marketplace(base),
        ".grok-plugin/marketplace.json": grok_marketplace(base),
        f"{PLUGIN_DIR}/.claude-plugin/plugin.json": claude_plugin(base),
        f"{PLUGIN_DIR}/.mcp.json": claude_mcp(base),
        f"{PLUGIN_DIR}/.codex-plugin/plugin.json": codex_plugin(base),
        f"{PLUGIN_DIR}/{CODEX_MCP}": codex_mcp(base),
        f"{PLUGIN_DIR}/.cursor-plugin/plugin.json": cursor_plugin(base),
        f"{PLUGIN_DIR}/.grok-plugin/plugin.json": grok_plugin(base),
        f"{PLUGIN_DIR}/{GROK_MCP}": grok_mcp(base),
        "mcpb/manifest.json": mcpb_manifest(base),
    }


def serialise(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if any generated file is stale")
    args = parser.parse_args(argv)

    stale: list[str] = []
    for rel, data in render(load_base()).items():
        path = ROOT / rel
        expected = serialise(data)
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current == expected:
            continue
        if args.check:
            stale.append(rel)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")
            print(f"wrote {rel}")

    for rel in stale:
        print(f"error: {rel} is out of date; run scripts/sync_plugin_manifests.py", file=sys.stderr)
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
