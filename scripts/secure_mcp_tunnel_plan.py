from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


SECURE_TUNNEL_DOC_URL = "https://developers.openai.com/api/docs/guides/secure-mcp-tunnels"
CONNECT_CHATGPT_DOC_URL = "https://developers.openai.com/apps-sdk/deploy/connect-chatgpt"
AUTH_DOC_URL = "https://developers.openai.com/apps-sdk/build/auth"


def build_tunnel_plan(repo_root: Path) -> dict[str, object]:
    mcp_command = "python scripts/run_chatgpt_mcp_server.py"
    service_url = os.environ.get("ICLOUD_INDEX_SERVICE_URL", "http://127.0.0.1:8080")

    return {
        "connector_name": "iCloudPlugin",
        "connector_description": (
            "Search indexed iCloudPlugin files, notes, bundles, and live readiness "
            "through the private cloud-vault MCP bridge."
        ),
        "local_mcp_command": mcp_command,
        "local_mcp_transport": "stdio",
        "repo_root": str(repo_root),
        "service_url": service_url,
        "requires_local_service_token": bool(os.environ.get("ICLOUD_INDEX_API_TOKEN")),
        "required_local_env": [
            "ICLOUD_INDEX_SERVICE_URL",
            "ICLOUD_INDEX_API_TOKEN",
        ],
        "chatgpt_steps": [
            "Open ChatGPT on the web and go to Settings -> Connectors -> Create.",
            "Choose the Tunnel option when creating the connector.",
            "Use the connector name and description from this plan.",
            f"Use the local MCP command: {mcp_command}",
            "Start a new ChatGPT conversation after the connector is created.",
        ],
        "official_docs": {
            "secure_mcp_tunnel": SECURE_TUNNEL_DOC_URL,
            "connect_from_chatgpt": CONNECT_CHATGPT_DOC_URL,
            "auth_reference": AUTH_DOC_URL,
        },
        "notes": [
            "Secure MCP Tunnel is the recommended easy path for a private or on-prem MCP server.",
            "This repo keeps the MCP server private and reuses the checked-in apps.mcp bridge.",
            "If the local index service expects plugin auth, export ICLOUD_INDEX_API_TOKEN before starting the MCP server.",
        ],
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Print the recommended Secure MCP Tunnel setup plan for connecting "
            "iCloudPlugin to ChatGPT."
        )
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the plan as JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    plan = build_tunnel_plan(repo_root)

    if args.json:
        print(json.dumps(plan, indent=2))
        return 0

    print("Secure MCP Tunnel plan for iCloudPlugin")
    print()
    print(f"Connector name: {plan['connector_name']}")
    print(f"Description: {plan['connector_description']}")
    print(f"Repo root: {plan['repo_root']}")
    print(f"Local MCP command: {plan['local_mcp_command']}")
    print(f"Service URL: {plan['service_url']}")
    print()
    print("Set these local environment variables before starting the MCP server if needed:")
    for env_name in plan["required_local_env"]:
        print(f"- {env_name}")
    print()
    print("ChatGPT setup steps:")
    for index, step in enumerate(plan["chatgpt_steps"], start=1):
        print(f"{index}. {step}")
    print()
    print("Official docs:")
    docs = plan["official_docs"]
    print(f"- Secure MCP Tunnel: {docs['secure_mcp_tunnel']}")
    print(f"- Connect from ChatGPT: {docs['connect_from_chatgpt']}")
    print(f"- Auth reference: {docs['auth_reference']}")
    print()
    print("Run this locally to start the MCP bridge:")
    print(plan["local_mcp_command"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
