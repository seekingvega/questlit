"""Questrade API client.

Authenticates with a single-use OAuth refresh token and fetches account positions.
The refresh token rotates on every redemption, so this module persists the
rotated token (plus a cached access token) to disk between calls.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

import requests

DEFAULT_TOKEN_PATH = Path.home() / ".questlit" / "token.json"
AUTH_URL = "https://login.questrade.com/oauth2/token"
REFRESH_LEEWAY_SECONDS = 60


class QuestradeAuthError(RuntimeError):
    """Raised when no usable refresh token is available."""


class QuestradeClient:
    """Client for Questrade's REST API.

    On first use, the client needs a refresh token generated in the Questrade
    portal (My Apps → Personal Apps). Provide it via ``seed_refresh_token`` for
    programmatic use, or wire ``prompt_callback`` to ask the user interactively
    when no cached token is available (or the cached one has been rejected).
    After the first successful call, the rotated refresh token plus a
    short-lived access token are written to ``token_path`` (default
    ``~/.questlit/token.json``) and reused on subsequent runs.

    Args:
        token_path: Where to read/write the persistent token cache.
        seed_refresh_token: Initial refresh token. Used only when the cache has
            no usable ``refresh_token``.
        prompt_callback: Called to obtain a fresh refresh token when no cache
            exists or the cached refresh token is rejected by Questrade. The
            callable receives no arguments and must return the token string.

    Example:
        >>> client = QuestradeClient(token_path=Path("/tmp/nope.json"),
        ...                          seed_refresh_token="seed")  # doctest: +SKIP
        >>> client.get_all_positions()  # doctest: +SKIP
    """

    def __init__(
        self,
        token_path: Path | None = None,
        seed_refresh_token: str | None = None,
        prompt_callback: Callable[[], str] | None = None,
    ) -> None:
        self.token_path = Path(token_path) if token_path else DEFAULT_TOKEN_PATH
        self._seed_refresh_token = seed_refresh_token
        self._prompt_callback = prompt_callback

    # ----- Public API -----

    def get_accounts(self) -> list[dict[str, Any]]:
        """Return the list of Questrade accounts for the authenticated user."""
        return self._get("v1/accounts").get("accounts", [])

    def get_positions(self, account_id: str | int) -> list[dict[str, Any]]:
        """Return open positions for a single account."""
        return self._get(f"v1/accounts/{account_id}/positions").get("positions", [])

    def token_info(self) -> dict[str, Any] | None:
        """Return the persisted token dict, or None if nothing has been cached.

        Pure on-disk read — never triggers a refresh. Use this to inspect token
        state (e.g. show expiry) without rotating the single-use refresh token.
        """
        token = self._load_token()
        return token or None

    def get_all_positions(self) -> list[dict[str, Any]]:
        """Return positions across every account, tagged with account metadata.

        Each row is the raw Questrade position dict augmented with
        ``accountNumber`` and ``accountType`` so the caller can group/filter.
        """
        rows: list[dict[str, Any]] = []
        for account in self.get_accounts():
            number = account.get("number")
            if number is None:
                continue
            for pos in self.get_positions(number):
                rows.append(
                    {
                        "accountNumber": number,
                        "accountType": account.get("type"),
                        **pos,
                    }
                )
        return rows

    # ----- Token persistence -----

    def _load_token(self) -> dict[str, Any]:
        if not self.token_path.exists():
            return {}
        try:
            return json.loads(self.token_path.read_text())
        except json.JSONDecodeError:
            return {}

    def _save_token(self, token: dict[str, Any]) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(json.dumps(token, indent=2))
        try:
            self.token_path.chmod(0o600)
        except OSError:
            pass

    # ----- Auth -----

    def _exchange_refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """POST a refresh token to Questrade and persist the rotated pair.

        Persists the rotated token to disk before returning. Questrade refresh
        tokens are single-use, so failing to persist would lock the user out.
        """
        resp = requests.post(
            AUTH_URL,
            params={"grant_type": "refresh_token", "refresh_token": refresh_token},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        api_server = data["api_server"].rstrip("/") + "/"
        token = {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "api_server": api_server,
            "expires_at": time.time() + int(data["expires_in"]),
        }
        self._save_token(token)
        return token

    def _refresh_access_token(self) -> dict[str, Any]:
        """Refresh the cached token, prompting for a new seed if needed.

        Tries the cached refresh token first. If it's missing or rejected by
        Questrade with a 400 ``invalid_grant`` (cached token expired
        server-side), falls back to ``seed_refresh_token`` or
        ``prompt_callback``. Raises ``QuestradeAuthError`` when no recovery
        path is available.
        """
        cached = self._load_token()
        cached_refresh = cached.get("refresh_token")

        if cached_refresh:
            try:
                return self._exchange_refresh_token(cached_refresh)
            except requests.HTTPError as exc:
                resp = getattr(exc, "response", None)
                if resp is None or resp.status_code != 400:
                    raise
                # Cached refresh token rejected — fall through to seed/prompt.

        seed = self._seed_refresh_token
        if not seed and self._prompt_callback is not None:
            seed = self._prompt_callback()
        if not seed:
            raise QuestradeAuthError(
                "No refresh token available. Generate one in the Questrade "
                "portal (My Apps → Personal Apps) and pass it via "
                "prompt_callback or seed_refresh_token."
            )

        return self._exchange_refresh_token(seed)

    def _ensure_valid_token(self) -> dict[str, Any]:
        token = self._load_token()
        if (
            token.get("access_token")
            and token.get("api_server")
            and token.get("expires_at", 0) - REFRESH_LEEWAY_SECONDS > time.time()
        ):
            return token
        return self._refresh_access_token()

    # ----- HTTP -----

    def _get(self, path: str) -> dict[str, Any]:
        """GET ``{api_server}{path}``. Refreshes once and retries on 401."""
        token = self._ensure_valid_token()
        url = urljoin(token["api_server"], path)
        headers = {"Authorization": f"Bearer {token['access_token']}"}
        resp = requests.get(url, headers=headers, timeout=15)

        if resp.status_code == 401:
            token = self._refresh_access_token()
            url = urljoin(token["api_server"], path)
            headers = {"Authorization": f"Bearer {token['access_token']}"}
            resp = requests.get(url, headers=headers, timeout=15)

        resp.raise_for_status()
        return resp.json()
