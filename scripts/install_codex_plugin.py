from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_install_plan(repo_root: Path, plugin_name: str = "icloud-drive") -> dict[str, str]:
    plugin_root = repo_root / "plugins" / plugin_name
    plugin_manifest_path = plugin_root / ".codex-plugin" / "plugin.json"
    plugin_mcp_path = plugin_root / ".mcp.json"
    marketplace_path = repo_root / ".agents" / "plugins" / "marketplace.json"

    missing_paths = [
        str(path)
        for path in (plugin_root, plugin_manifest_path, plugin_mcp_path, marketplace_path)
        if not path.exists()
    ]
    if missing_paths:
        raise FileNotFoundError(
            "Missing required plugin files:\n" + "\n".join(missing_paths)
        )

    plugin_manifest = _load_json(plugin_manifest_path)
    marketplace = _load_json(marketplace_path)

    marketplace_plugins = marketplace.get("plugins", [])
    plugin_entry = next(
        (entry for entry in marketplace_plugins if entry.get("name") == plugin_name),
        None,
    )
    if plugin_entry is None:
        raise ValueError(
            f"Marketplace {marketplace_path} does not include a plugin entry for {plugin_name}."
        )

    source = plugin_entry.get("source", {})
    source_path = source.get("path")
    if source.get("source") != "local" or source_path != f"./plugins/{plugin_name}":
        raise ValueError(
            f"Expected local marketplace source ./plugins/{plugin_name}, got {source!r}."
        )

    plugin_manifest_name = plugin_manifest.get("name")
    if plugin_manifest_name != plugin_name:
        raise ValueError(
            f"Plugin manifest name mismatch: expected {plugin_name}, got {plugin_manifest_name!r}."
        )

    marketplace_name = marketplace.get("name")
    if not marketplace_name:
        raise ValueError(f"Marketplace {marketplace_path} is missing a top-level name.")

    plugin_version = plugin_manifest.get("version", "")
    if not plugin_version:
        raise ValueError(f"Plugin manifest {plugin_manifest_path} is missing a version.")

    marketplace_add_command = f'codex plugin marketplace add "{repo_root}"'
    plugin_add_command = f'codex plugin add "{plugin_name}@{marketplace_name}"'

    return {
        "plugin_name": plugin_name,
        "plugin_version": plugin_version,
        "plugin_root": str(plugin_root),
        "plugin_manifest_path": str(plugin_manifest_path),
        "marketplace_path": str(marketplace_path),
        "marketplace_name": marketplace_name,
        "marketplace_add_command": marketplace_add_command,
        "plugin_add_command": plugin_add_command,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the checked-in iCloud Drive Codex plugin and print the "
            "repo-local marketplace install commands."
        )
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the install plan as JSON.",
    )
    parser.add_argument(
        "--plugin-name",
        default="icloud-drive",
        help="Plugin name to validate within the checked-in marketplace.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    plan = build_install_plan(repo_root=repo_root, plugin_name=args.plugin_name)

    if args.json:
        print(json.dumps(plan, indent=2))
        return 0

    print(f"Plugin: {plan['plugin_name']} ({plan['plugin_version']})")
    print(f"Plugin root: {plan['plugin_root']}")
    print(f"Marketplace: {plan['marketplace_name']}")
    print(f"Marketplace file: {plan['marketplace_path']}")
    print()
    print("Run these commands in a Codex-capable terminal:")
    print(plan["marketplace_add_command"])
    print(plan["plugin_add_command"])
    print()
    print("After install or reinstall, start a new Codex thread so the plugin tools are picked up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
