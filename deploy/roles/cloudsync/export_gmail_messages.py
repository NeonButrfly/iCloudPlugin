#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


def _bootstrap_repo_imports() -> None:
    repo_root = Path(os.getenv("REPO_ROOT") or "/opt/iCloudPlugin").resolve()
    for candidate in (repo_root, repo_root / "src"):
        candidate_text = str(candidate)
        if candidate.exists() and candidate_text not in sys.path:
            sys.path.insert(0, candidate_text)


def main() -> int:
    _bootstrap_repo_imports()
    from icloud_index_service.services.gmail_export import main as gmail_export_main

    return gmail_export_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
