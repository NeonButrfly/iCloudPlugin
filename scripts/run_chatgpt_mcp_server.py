from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap_repo_imports() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for candidate in (repo_root, repo_root / "src"):
        candidate_text = str(candidate)
        if candidate_text not in sys.path:
            sys.path.insert(0, candidate_text)


_bootstrap_repo_imports()

from apps.mcp.server import main


if __name__ == "__main__":
    main()
