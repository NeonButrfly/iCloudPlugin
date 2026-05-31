from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from icloud_index_service.services.product_readiness import build_product_readiness_report


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fetch_json(url: str, *, api_token: str | None, timeout_seconds: float) -> dict:
    headers = {"Accept": "application/json"}
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def _load_summary_payload(
    *,
    summary_file: Path | None,
    summary_url: str | None,
    timeout_seconds: float,
) -> tuple[dict | None, dict[str, object] | None]:
    if summary_file is not None:
        try:
            return json.loads(summary_file.read_text(encoding="utf-8")), None
        except (OSError, json.JSONDecodeError) as exc:
            return None, {
                "source": str(summary_file),
                "error": "summary-file-invalid",
                "detail": str(exc),
            }

    if summary_url:
        try:
            payload = _fetch_json(
                summary_url,
                api_token=(os.getenv("PLUGIN_API_TOKEN") or "").strip() or None,
                timeout_seconds=timeout_seconds,
            )
            return payload, None
        except HTTPError as exc:
            return None, {
                "source": summary_url,
                "error": "summary-url-http-error",
                "detail": f"{exc.code} {exc.reason}",
            }
        except URLError as exc:
            return None, {
                "source": summary_url,
                "error": "summary-url-unreachable",
                "detail": str(exc.reason),
            }
        except json.JSONDecodeError as exc:
            return None, {
                "source": summary_url,
                "error": "summary-url-invalid-json",
                "detail": str(exc),
            }

    return None, None


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report current cloud-vault product readiness from repo artifacts plus an optional authenticated status summary."
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Repo root to inspect. Defaults to the current script's parent repo.",
    )
    parser.add_argument(
        "--summary-file",
        help="Optional path to a saved /status/summary or report_live_status JSON payload.",
    )
    parser.add_argument(
        "--summary-url",
        help="Optional authenticated /status/summary URL. Uses PLUGIN_API_TOKEN from the environment when present.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=8.0,
        help="Network timeout for --summary-url. Default: 8.",
    )
    parser.add_argument(
        "--json-out",
        help="Optional path to write the full JSON report.",
    )
    return parser


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    summary_file = Path(args.summary_file).resolve() if args.summary_file else None
    summary_payload, summary_error = _load_summary_payload(
        summary_file=summary_file,
        summary_url=args.summary_url,
        timeout_seconds=args.timeout_seconds,
    )

    report = build_product_readiness_report(
        repo_root=repo_root,
        summary_payload=summary_payload,
        cloudflare_api_token_present=bool((os.getenv("CLOUDFLARE_API_TOKEN") or "").strip()),
    )
    report["recorded_at"] = _utc_now_iso()
    report["inputs"] = {
        "repo_root": str(repo_root),
        "summary_file": str(summary_file) if summary_file else None,
        "summary_url": args.summary_url,
        "summary_loaded": summary_payload is not None,
        "summary_error": summary_error,
        "plugin_api_token_present": bool((os.getenv("PLUGIN_API_TOKEN") or "").strip()),
        "cloudflare_api_token_present": bool((os.getenv("CLOUDFLARE_API_TOKEN") or "").strip()),
    }

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.json_out:
        output_path = Path(args.json_out).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
