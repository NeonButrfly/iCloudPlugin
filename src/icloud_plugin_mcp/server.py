from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="icloud-plugin-mcp-stub",
        description="Task 1 stub MCP entrypoint for the iCloud Drive plugin scaffold.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the Task 1 stub version and exit.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.version:
        print("icloud-plugin-mcp-stub 0.1.0")
        return 0

    print("icloud-plugin-mcp-stub: Task 1 placeholder entrypoint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
