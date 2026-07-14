from __future__ import annotations

import argparse
import json
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer
from pathlib import Path
from typing import Any
from urllib import error
from urllib import parse
from urllib import request


GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


def _load_client_secret(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Client secret file {path} did not contain a JSON object.")
    web_payload = payload.get("installed") or payload.get("web")
    if not isinstance(web_payload, dict):
        raise ValueError(
            f"Client secret file {path} did not contain an installed/web OAuth client object."
        )

    client_id = str(web_payload.get("client_id") or "").strip()
    client_secret = str(web_payload.get("client_secret") or "").strip()
    auth_uri = str(web_payload.get("auth_uri") or GOOGLE_AUTH_URI).strip()
    token_uri = str(web_payload.get("token_uri") or GOOGLE_TOKEN_URI).strip()
    if not client_id or not client_secret:
        raise ValueError(f"Client secret file {path} is missing client_id or client_secret.")

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "auth_uri": auth_uri,
        "token_uri": token_uri,
    }


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    server_version = "GmailAuthorizedUserHelper/1.0"

    def do_GET(self) -> None:  # noqa: N802
        query = parse.urlparse(self.path).query
        params = parse.parse_qs(query)
        self.server.oauth_params = {key: values[-1] for key, values in params.items() if values}  # type: ignore[attr-defined]
        if "error" in self.server.oauth_params:  # type: ignore[attr-defined]
            body = "Google returned an error. You can close this tab and return to the terminal."
        else:
            body = "Authorization received. You can close this tab and return to the terminal."

        response = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def _wait_for_callback(listen_host: str, listen_port: int) -> dict[str, str]:
    httpd = HTTPServer((listen_host, listen_port), _OAuthCallbackHandler)
    httpd.oauth_params = {}  # type: ignore[attr-defined]
    try:
        httpd.handle_request()
        return dict(httpd.oauth_params)  # type: ignore[attr-defined]
    finally:
        httpd.server_close()


def _build_authorization_url(
    *,
    client_id: str,
    auth_uri: str,
    redirect_uri: str,
    state: str,
    login_hint: str,
) -> str:
    query = parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GMAIL_READONLY_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "login_hint": login_hint or None,
        }
    )
    return f"{auth_uri}?{query}"


def _exchange_code_for_token(
    *,
    token_uri: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
) -> dict[str, Any]:
    body = parse.urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    req = request.Request(
        token_uri,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _write_authorized_user_file(
    destination: Path,
    *,
    client_id: str,
    client_secret: str,
    token_uri: str,
    token_payload: dict[str, Any],
) -> None:
    refresh_token = str(token_payload.get("refresh_token") or "").strip()
    if not refresh_token:
        raise ValueError(
            "Google did not return a refresh_token. Remove any prior grant for this app/account and try again."
        )

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "token_uri": token_uri,
        "type": "authorized_user",
        "scopes": [GMAIL_READONLY_SCOPE],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a local Google OAuth consent flow and write a Gmail authorized-user JSON file."
    )
    parser.add_argument(
        "--client-secret-file",
        required=True,
        help="Path to the Google OAuth client secret JSON downloaded from Google Cloud Console.",
    )
    parser.add_argument(
        "--account-email",
        required=True,
        help="Google account to authorize, used as a login hint and for output naming.",
    )
    parser.add_argument(
        "--output-file",
        required=True,
        help="Where to write the authorized-user JSON file.",
    )
    parser.add_argument(
        "--listen-host",
        default="127.0.0.1",
        help="Local host for the temporary OAuth callback listener. Default: 127.0.0.1",
    )
    parser.add_argument(
        "--listen-port",
        type=int,
        default=8765,
        help="Local port for the temporary OAuth callback listener. Default: 8765",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not auto-open the browser; print the consent URL instead.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    client_secret = _load_client_secret(Path(args.client_secret_file).expanduser())
    redirect_uri = f"http://{args.listen_host}:{args.listen_port}/oauth2/callback"
    state = secrets.token_urlsafe(24)
    authorization_url = _build_authorization_url(
        client_id=client_secret["client_id"],
        auth_uri=client_secret["auth_uri"],
        redirect_uri=redirect_uri,
        state=state,
        login_hint=str(args.account_email or "").strip(),
    )

    print("Open this URL in your browser and complete Google consent:")
    print(authorization_url)
    print("")
    print(f"Expected redirect URI: {redirect_uri}")
    print(f"Requested scope: {GMAIL_READONLY_SCOPE}")
    print("")

    if not args.no_browser:
        webbrowser.open(authorization_url, new=1, autoraise=True)

    print("Waiting for Google to redirect back to the local callback...")
    callback_params = _wait_for_callback(args.listen_host, args.listen_port)

    returned_state = str(callback_params.get("state") or "")
    if returned_state != state:
        raise ValueError("OAuth callback state mismatch. Aborting.")
    if "error" in callback_params:
        raise ValueError(f"Google returned an OAuth error: {callback_params['error']}")

    code = str(callback_params.get("code") or "").strip()
    if not code:
        raise ValueError("OAuth callback did not include an authorization code.")

    try:
        token_payload = _exchange_code_for_token(
            token_uri=client_secret["token_uri"],
            client_id=client_secret["client_id"],
            client_secret=client_secret["client_secret"],
            redirect_uri=redirect_uri,
            code=code,
        )
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"Token exchange failed with HTTP {exc.code}: {detail}") from exc

    output_file = Path(args.output_file).expanduser()
    _write_authorized_user_file(
        output_file,
        client_id=client_secret["client_id"],
        client_secret=client_secret["client_secret"],
        token_uri=client_secret["token_uri"],
        token_payload=token_payload,
    )

    print(f"Wrote Gmail authorized-user JSON to: {output_file}")
    print("Copy this file to kayraspi2 at the matching configured path when ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
