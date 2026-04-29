"""Questrade API client.

Authenticates with a single-use OAuth refresh token and fetches account positions.
The refresh token rotates on every redemption, so this module persists the
rotated token (plus a cached access token) to disk between calls.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import urljoin

import requests

DEFAULT_TOKEN_PATH = Path.home() / ".questlit" / "token.json"
AUTH_URL = "https://login.questrade.com/oauth2/token"
REFRESH_LEEWAY_SECONDS = 60
ACTIVITIES_MAX_WINDOW_DAYS = 30


def _ensure_aware(dt: datetime) -> datetime:
    """Return ``dt`` unchanged if timezone-aware; else attach UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _chunk_date_range(
    start: datetime, end: datetime, max_days: int = ACTIVITIES_MAX_WINDOW_DAYS
) -> Iterator[tuple[datetime, datetime]]:
    """Yield ``(chunk_start, chunk_end)`` pairs covering ``[start, end)``.

    Each chunk spans at most ``max_days`` days. Adjacent chunks share an edge
    (one chunk's ``end`` equals the next chunk's ``start``) so the union covers
    the full range with no gaps and no overlaps. Yields nothing when
    ``start >= end``.

    Args:
        start: Range start (inclusive).
        end: Range end (exclusive).
        max_days: Maximum span of a single chunk, in days.

    Yields:
        Tuples of (chunk_start, chunk_end) datetimes.

    Example:
        >>> from datetime import datetime, timezone
        >>> s = datetime(2025, 1, 1, tzinfo=timezone.utc)
        >>> e = datetime(2025, 3, 17, tzinfo=timezone.utc)
        >>> [(a.day, b.day) for a, b in _chunk_date_range(s, e, max_days=30)]
        [(1, 31), (31, 2), (2, 17)]
    """
    step = timedelta(days=max_days)
    while start < end:
        chunk_end = min(start + step, end)
        yield start, chunk_end
        start = chunk_end


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

    def get_balances(self, account_id: str | int) -> dict[str, Any]:
        """Return the raw balances payload for a single account.

        Questrade's balances response has four sibling lists —
        ``perCurrencyBalances`` and ``combinedBalances`` (live), plus
        ``sodPerCurrencyBalances`` and ``sodCombinedBalances`` (start of
        day) — so this method returns the full dict unchanged. Use
        :meth:`get_all_balances` for a flattened cross-account view.

        Args:
            account_id: Questrade account number.

        Returns:
            The full balances payload dict.
        """
        return self._get(f"v1/accounts/{account_id}/balances")

    def get_orders(
        self,
        account_id: str | int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        state_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return orders for a single account.

        With no arguments, Questrade returns its default set (active orders).
        Pass ``state_filter="All"`` to include closed/cancelled orders, or a
        date range to restrict the window. All arguments are forwarded to
        Questrade unchanged — this method is intentionally unopinionated.

        Args:
            account_id: Questrade account number.
            start_time: Optional start of the order window. Naive datetimes
                are treated as UTC.
            end_time: Optional end of the order window. Naive datetimes are
                treated as UTC.
            state_filter: One of ``"All"``, ``"Open"``, or ``"Closed"``.

        Returns:
            List of raw order dicts from Questrade.
        """
        params: dict[str, Any] = {}
        if start_time is not None:
            params["startTime"] = _ensure_aware(start_time).isoformat()
        if end_time is not None:
            params["endTime"] = _ensure_aware(end_time).isoformat()
        if state_filter is not None:
            params["stateFilter"] = state_filter
        return self._get(
            f"v1/accounts/{account_id}/orders",
            params=params or None,
        ).get("orders", [])

    def get_activities(
        self,
        account_id: str | int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return account activities, auto-chunked across long ranges.

        Questrade's activities endpoint requires both ``startTime`` and
        ``endTime`` and rejects windows longer than 31 days. This method
        defaults to the last 30 days when either bound is omitted, and splits
        longer ranges into ≤30-day chunks under the hood, concatenating the
        results.

        Args:
            account_id: Questrade account number.
            start_time: Window start. Defaults to ``end_time - 30 days``.
                Naive datetimes are treated as UTC.
            end_time: Window end. Defaults to "now" in UTC. Naive datetimes
                are treated as UTC.

        Returns:
            List of raw activity dicts spanning the requested window.
        """
        if end_time is None:
            end_time = datetime.now(tz=timezone.utc)
        if start_time is None:
            start_time = end_time - timedelta(days=ACTIVITIES_MAX_WINDOW_DAYS)
        start_time = _ensure_aware(start_time)
        end_time = _ensure_aware(end_time)

        path = f"v1/accounts/{account_id}/activities"
        rows: list[dict[str, Any]] = []
        for chunk_start, chunk_end in _chunk_date_range(start_time, end_time):
            payload = self._get(
                path,
                params={
                    "startTime": chunk_start.isoformat(),
                    "endTime": chunk_end.isoformat(),
                },
            )
            rows.extend(payload.get("activities", []))
        return rows

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

    def get_all_balances(self) -> list[dict[str, Any]]:
        """Return per-currency live balances across every account.

        Each row is a Questrade ``perCurrencyBalances`` entry augmented
        with ``accountNumber`` and ``accountType`` for grouping/filtering.
        For combined or start-of-day views, call :meth:`get_balances`
        directly.
        """
        rows: list[dict[str, Any]] = []
        for account in self.get_accounts():
            number = account.get("number")
            if number is None:
                continue
            payload = self.get_balances(number)
            for bal in payload.get("perCurrencyBalances", []):
                rows.append(
                    {
                        "accountNumber": number,
                        "accountType": account.get("type"),
                        **bal,
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

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET ``{api_server}{path}``. Refreshes once and retries on 401."""
        token = self._ensure_valid_token()
        url = urljoin(token["api_server"], path)
        headers = {"Authorization": f"Bearer {token['access_token']}"}
        resp = requests.get(url, headers=headers, params=params, timeout=15)

        if resp.status_code == 401:
            token = self._refresh_access_token()
            url = urljoin(token["api_server"], path)
            headers = {"Authorization": f"Bearer {token['access_token']}"}
            resp = requests.get(url, headers=headers, params=params, timeout=15)

        resp.raise_for_status()
        return resp.json()
