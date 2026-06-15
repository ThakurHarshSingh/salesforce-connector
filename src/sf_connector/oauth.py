"""Salesforce OAuth 2.0 Authorization Code flow — the "Connect Salesforce" button.

This is the user-facing login flow (the same UX as "Login with Google"):

    1. Send the user to Salesforce's authorize page.
    2. The user logs in and clicks "Allow".
    3. Salesforce redirects back to our callback URL with a one-time `code`.
    4. We exchange that `code` for an `access_token` + `refresh_token`.

In the product, steps 1 and 3 happen in the user's browser against the Auditify
backend. Here we run a tiny local web server so the exact same flow is runnable
from the CLI for testing and as a reference implementation for the frontend team.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx

from .config import Settings


@dataclass
class OAuthTokens:
    """The result of a successful Salesforce login."""

    access_token: str
    refresh_token: str | None
    instance_url: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "instance_url": self.instance_url,
            },
            indent=2,
        )

    @classmethod
    def from_file(cls, path: Path) -> OAuthTokens:
        data = json.loads(path.read_text())
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            instance_url=data["instance_url"],
        )


def _pkce_pair() -> tuple[str, str]:
    """Return a (code_verifier, code_challenge) PKCE pair (S256).

    Salesforce External Client Apps require PKCE: we send the challenge on the
    authorize request and prove possession with the verifier at token exchange.
    """
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _authorize_url(settings: Settings, state: str, code_challenge: str) -> str:
    """Build the Salesforce authorize URL the user's browser is sent to."""
    params = {
        "response_type": "code",
        "client_id": settings.sf_client_id,
        "redirect_uri": settings.sf_redirect_uri,
        "scope": "api refresh_token",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    base = f"{settings.sf_login_base_url}/services/oauth2/authorize"
    return f"{base}?{urllib.parse.urlencode(params)}"


def _exchange_code(settings: Settings, code: str, code_verifier: str) -> OAuthTokens:
    """Swap the one-time authorization `code` for tokens (the backend's job)."""
    token_url = f"{settings.sf_login_base_url}/services/oauth2/token"
    response = httpx.post(
        token_url,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": settings.sf_client_id,
            "client_secret": settings.sf_client_secret,
            "redirect_uri": settings.sf_redirect_uri,
            "code_verifier": code_verifier,
        },
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    return OAuthTokens(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token"),
        instance_url=payload["instance_url"],
    )


def refresh_tokens(settings: Settings, refresh_token: str) -> OAuthTokens:
    """Mint a fresh access token from a stored refresh token.

    Salesforce access tokens (sessions) expire; a long-lived connection must
    refresh them. The refresh response returns a new `access_token` but reuses
    the existing `refresh_token`, so we carry it forward.
    """
    token_url = f"{settings.sf_login_base_url}/services/oauth2/token"
    response = httpx.post(
        token_url,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.sf_client_id,
            "client_secret": settings.sf_client_secret,
        },
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    return OAuthTokens(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token") or refresh_token,
        instance_url=payload["instance_url"],
    )


def revoke_token(settings: Settings, token: str) -> None:
    """Revoke an access or refresh token at Salesforce (used on disconnect).

    Revoking the refresh token invalidates the whole grant, so future syncs stop
    — what the product's "Delete connection" must do, not just forget the token.
    """
    revoke_url = f"{settings.sf_login_base_url}/services/oauth2/revoke"
    response = httpx.post(revoke_url, data={"token": token}, timeout=30.0)
    response.raise_for_status()


class _CallbackHandler(BaseHTTPRequestHandler):
    """Captures the single redirect Salesforce makes back to us."""

    # Set by login() before the server starts.
    captured: dict[str, str] = {}
    expected_state: str = ""

    def do_GET(self) -> None:  # noqa: N802 - http.server's required name
        query = urllib.parse.urlparse(self.path).query
        params = dict(urllib.parse.parse_qsl(query))

        # Ignore stray requests (e.g. favicon) that carry neither code nor error,
        # so a leftover browser tab can't end the wait prematurely.
        if "code" not in params and "error" not in params:
            self._respond("Waiting for Salesforce... you can close this tab.")
            return
        # On localhost the loopback redirect can't be intercepted and PKCE already
        # binds the code to this client, so a stale `state` (from a prior attempt)
        # is a warning, not a failure. A production backend MUST reject mismatches.
        if params.get("state") != self.expected_state:
            print("Warning: OAuth state did not match (likely a stale browser tab). Continuing.")
        if "error" in params:
            _CallbackHandler.captured = params
            self._respond(f"Login failed: {params['error']}. You can close this tab.")
            return
        if "code" in params:
            _CallbackHandler.captured = params
            self._respond(
                "✓ Salesforce connected. You can close this tab and return to the terminal."
            )

    def _respond(self, message: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"<html><body><h2>{message}</h2></body></html>".encode())

    def log_message(self, *args: object) -> None:  # silence default stderr logging
        pass


def login(settings: Settings) -> OAuthTokens:
    """Run the full Authorization Code flow locally and return the tokens.

    Opens the user's browser to Salesforce, waits for the redirect, exchanges the
    code, caches the tokens, and returns them. Mirrors exactly what the Auditify
    backend will do behind the "Connect Salesforce" button.
    """
    redirect = urllib.parse.urlparse(settings.sf_redirect_uri)
    host = redirect.hostname or "localhost"
    port = redirect.port or 1717

    state = secrets.token_urlsafe(16)
    code_verifier, code_challenge = _pkce_pair()
    _CallbackHandler.captured = {}
    _CallbackHandler.expected_state = state

    url = _authorize_url(settings, state, code_challenge)
    print(f"Opening browser to log in to Salesforce...\nIf it doesn't open, visit:\n{url}\n")
    webbrowser.open(url)

    # Serve exactly one request: the redirect back from Salesforce.
    server = HTTPServer((host, port), _CallbackHandler)
    try:
        while not _CallbackHandler.captured:
            server.handle_request()
    finally:
        server.server_close()

    captured = _CallbackHandler.captured
    if "error" in captured:
        raise RuntimeError(
            f"Salesforce returned: {captured.get('error')} "
            f"({captured.get('error_description', 'no description')})"
        )
    if "code" not in captured:
        raise RuntimeError("No authorization code was received.")

    tokens = _exchange_code(settings, captured["code"], code_verifier)
    settings.sf_token_cache.write_text(tokens.to_json())
    return tokens
