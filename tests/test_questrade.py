"""Tests for questlit.questrade.

HTTP is mocked at the ``requests.post`` / ``requests.get`` boundary so the
tests are hermetic. ``tmp_path`` isolates each test's token file.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

from questlit.questrade import (
    QuestradeAuthError,
    QuestradeClient,
    _chunk_date_range,
)


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    if status_code >= 400:
        err = requests.HTTPError(f"HTTP {status_code}")
        err.response = resp
        resp.raise_for_status.side_effect = err
    else:
        resp.raise_for_status.return_value = None
    return resp


def _refresh_payload(refresh_token: str = "rotated-token") -> dict:
    return {
        "access_token": "access-abc",
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": 1800,
        "api_server": "https://api01.iq.questrade.com",
    }


def test_refresh_persists_rotated_refresh_token(tmp_path):
    """The new refresh token from the response must be written to disk."""
    token_path = tmp_path / "token.json"
    client = QuestradeClient(token_path=token_path, seed_refresh_token="seed")

    with patch(
        "questlit.questrade.requests.post",
        return_value=_mock_response(200, _refresh_payload("new-refresh")),
    ) as post:
        client._refresh_access_token()

    assert post.call_args.kwargs["params"]["refresh_token"] == "seed"
    persisted = json.loads(token_path.read_text())
    assert persisted["refresh_token"] == "new-refresh"
    assert persisted["access_token"] == "access-abc"
    assert persisted["api_server"].endswith(".questrade.com/")
    assert persisted["expires_at"] > time.time()


def test_ensure_valid_token_uses_cache_when_fresh(tmp_path):
    token_path = tmp_path / "token.json"
    token_path.write_text(
        json.dumps(
            {
                "access_token": "cached",
                "refresh_token": "r",
                "api_server": "https://api01.iq.questrade.com/",
                "expires_at": time.time() + 1000,
            }
        )
    )
    client = QuestradeClient(token_path=token_path)

    with patch("questlit.questrade.requests.post") as post:
        token = client._ensure_valid_token()

    assert token["access_token"] == "cached"
    post.assert_not_called()


def test_ensure_valid_token_refreshes_when_near_expiry(tmp_path):
    token_path = tmp_path / "token.json"
    token_path.write_text(
        json.dumps(
            {
                "access_token": "stale",
                "refresh_token": "r",
                "api_server": "https://api01.iq.questrade.com/",
                "expires_at": time.time() + 5,  # within leeway
            }
        )
    )
    client = QuestradeClient(token_path=token_path)

    with patch(
        "questlit.questrade.requests.post",
        return_value=_mock_response(200, _refresh_payload()),
    ) as post:
        token = client._ensure_valid_token()

    post.assert_called_once()
    assert token["access_token"] == "access-abc"


def test_get_positions_hits_correct_url(tmp_path):
    token_path = tmp_path / "token.json"
    token_path.write_text(
        json.dumps(
            {
                "access_token": "access-abc",
                "refresh_token": "r",
                "api_server": "https://api01.iq.questrade.com/",
                "expires_at": time.time() + 1000,
            }
        )
    )
    client = QuestradeClient(token_path=token_path)

    positions_payload = {"positions": [{"symbol": "AAPL", "openQuantity": 10}]}
    with patch(
        "questlit.questrade.requests.get",
        return_value=_mock_response(200, positions_payload),
    ) as get:
        result = client.get_positions("12345")

    assert result == positions_payload["positions"]
    called_url = get.call_args.args[0]
    assert called_url == "https://api01.iq.questrade.com/v1/accounts/12345/positions"
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer access-abc"


def test_get_retries_once_on_401(tmp_path):
    token_path = tmp_path / "token.json"
    token_path.write_text(
        json.dumps(
            {
                "access_token": "expired",
                "refresh_token": "r",
                "api_server": "https://api01.iq.questrade.com/",
                "expires_at": time.time() + 1000,
            }
        )
    )
    client = QuestradeClient(token_path=token_path)

    get_responses = [
        _mock_response(401, {}),
        _mock_response(200, {"accounts": [{"number": "1"}]}),
    ]
    with patch(
        "questlit.questrade.requests.get", side_effect=get_responses
    ) as get, patch(
        "questlit.questrade.requests.post",
        return_value=_mock_response(200, _refresh_payload("rotated")),
    ) as post:
        result = client.get_accounts()

    assert result == [{"number": "1"}]
    assert get.call_count == 2
    post.assert_called_once()
    # Second GET used the refreshed access token
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer access-abc"


def test_seed_token_used_only_when_file_missing(tmp_path):
    token_path = tmp_path / "token.json"

    # No file, no seed, no callback → should raise
    client = QuestradeClient(token_path=token_path)
    with pytest.raises(QuestradeAuthError):
        client._refresh_access_token()

    # Constructor seed picked up when cache is empty
    client = QuestradeClient(token_path=token_path, seed_refresh_token="from-arg")
    with patch(
        "questlit.questrade.requests.post",
        return_value=_mock_response(200, _refresh_payload()),
    ) as post:
        client._refresh_access_token()
    assert post.call_args.kwargs["params"]["refresh_token"] == "from-arg"

    # On the next refresh, the seed is ignored — disk wins.
    with patch(
        "questlit.questrade.requests.post",
        return_value=_mock_response(200, _refresh_payload("rotated-2")),
    ) as post:
        client._refresh_access_token()
    assert post.call_args.kwargs["params"]["refresh_token"] == "rotated-token"


def test_prompt_callback_used_when_no_cached_token(tmp_path):
    """When the cache is empty and no seed is set, the callback supplies one."""
    token_path = tmp_path / "token.json"
    callback = MagicMock(return_value="FRESH_SEED")
    client = QuestradeClient(token_path=token_path, prompt_callback=callback)

    with patch(
        "questlit.questrade.requests.post",
        return_value=_mock_response(200, _refresh_payload("rotated")),
    ) as post:
        client._refresh_access_token()

    callback.assert_called_once_with()
    assert post.call_args.kwargs["params"]["refresh_token"] == "FRESH_SEED"
    persisted = json.loads(token_path.read_text())
    assert persisted["refresh_token"] == "rotated"


def test_prompt_callback_used_when_cached_refresh_rejected(tmp_path):
    """A 400 from Questrade on the cached token triggers the prompt fallback."""
    token_path = tmp_path / "token.json"
    token_path.write_text(
        json.dumps(
            {
                "access_token": "stale-access",
                "refresh_token": "stale-refresh",
                "api_server": "https://api01.iq.questrade.com/",
                "expires_at": time.time() - 10,  # forces a refresh
            }
        )
    )
    callback = MagicMock(return_value="FRESH_SEED")
    client = QuestradeClient(token_path=token_path, prompt_callback=callback)

    post_responses = [
        _mock_response(400, {"error": "invalid_grant"}),
        _mock_response(200, _refresh_payload("rotated")),
    ]
    with patch(
        "questlit.questrade.requests.post", side_effect=post_responses
    ) as post:
        client._refresh_access_token()

    callback.assert_called_once_with()
    assert post.call_count == 2
    # First call used the cached (rejected) token, second used the prompt seed.
    assert post.call_args_list[0].kwargs["params"]["refresh_token"] == "stale-refresh"
    assert post.call_args_list[1].kwargs["params"]["refresh_token"] == "FRESH_SEED"
    persisted = json.loads(token_path.read_text())
    assert persisted["refresh_token"] == "rotated"


def test_raises_when_no_callback_and_no_seed_and_no_cache(tmp_path):
    """Programmatic use with no recovery path still raises QuestradeAuthError."""
    client = QuestradeClient(token_path=tmp_path / "token.json")
    with pytest.raises(QuestradeAuthError):
        client._refresh_access_token()


def test_prompt_token_rejected_does_not_loop(tmp_path):
    """If the prompted seed is also rejected, raise without re-prompting."""
    token_path = tmp_path / "token.json"
    callback = MagicMock(return_value="ALSO_BAD")
    client = QuestradeClient(token_path=token_path, prompt_callback=callback)

    with patch(
        "questlit.questrade.requests.post",
        return_value=_mock_response(400, {"error": "invalid_grant"}),
    ) as post:
        with pytest.raises(requests.HTTPError):
            client._refresh_access_token()

    callback.assert_called_once_with()
    post.assert_called_once()


def test_token_info_returns_none_when_missing(tmp_path):
    client = QuestradeClient(token_path=tmp_path / "token.json")
    with patch("questlit.questrade.requests.post") as post:
        assert client.token_info() is None
    post.assert_not_called()


def test_token_info_returns_disk_state_without_refresh(tmp_path):
    token_path = tmp_path / "token.json"
    payload = {
        "access_token": "cached",
        "refresh_token": "r",
        "api_server": "https://api01.iq.questrade.com/",
        "expires_at": time.time() + 1000,
    }
    token_path.write_text(json.dumps(payload))
    client = QuestradeClient(token_path=token_path)

    with patch("questlit.questrade.requests.post") as post:
        info = client.token_info()

    assert info == payload
    post.assert_not_called()


def _seed_token_file(token_path) -> None:
    token_path.write_text(
        json.dumps(
            {
                "access_token": "access-abc",
                "refresh_token": "r",
                "api_server": "https://api01.iq.questrade.com/",
                "expires_at": time.time() + 1000,
            }
        )
    )


def test_get_orders_omits_query_string_when_no_args(tmp_path):
    """No filter args → no `params=` payload, default Questrade behaviour."""
    token_path = tmp_path / "token.json"
    _seed_token_file(token_path)
    client = QuestradeClient(token_path=token_path)

    payload = {"orders": [{"id": 1, "state": "Executed"}]}
    with patch(
        "questlit.questrade.requests.get",
        return_value=_mock_response(200, payload),
    ) as get:
        result = client.get_orders("ACC")

    assert result == payload["orders"]
    called_url = get.call_args.args[0]
    assert called_url == "https://api01.iq.questrade.com/v1/accounts/ACC/orders"
    assert get.call_args.kwargs["params"] is None


def test_get_orders_passes_state_filter_and_times(tmp_path):
    """All optional args land in the query string in Questrade-native casing."""
    token_path = tmp_path / "token.json"
    _seed_token_file(token_path)
    client = QuestradeClient(token_path=token_path)

    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 1, 15, tzinfo=timezone.utc)

    with patch(
        "questlit.questrade.requests.get",
        return_value=_mock_response(200, {"orders": []}),
    ) as get:
        client.get_orders("ACC", start_time=start, end_time=end, state_filter="All")

    params = get.call_args.kwargs["params"]
    assert params == {
        "startTime": "2025-01-01T00:00:00+00:00",
        "endTime": "2025-01-15T00:00:00+00:00",
        "stateFilter": "All",
    }


def test_get_orders_attaches_utc_to_naive_datetimes(tmp_path):
    """Naive datetimes are treated as UTC when serialized to ISO."""
    token_path = tmp_path / "token.json"
    _seed_token_file(token_path)
    client = QuestradeClient(token_path=token_path)

    naive = datetime(2025, 1, 1)  # no tzinfo
    with patch(
        "questlit.questrade.requests.get",
        return_value=_mock_response(200, {"orders": []}),
    ) as get:
        client.get_orders("ACC", start_time=naive)

    assert get.call_args.kwargs["params"]["startTime"] == "2025-01-01T00:00:00+00:00"


def test_get_activities_default_range_calls_once(tmp_path):
    """No args → exactly one HTTP call covering the trailing 30 days."""
    token_path = tmp_path / "token.json"
    _seed_token_file(token_path)
    client = QuestradeClient(token_path=token_path)

    with patch(
        "questlit.questrade.requests.get",
        return_value=_mock_response(200, {"activities": [{"type": "Trades"}]}),
    ) as get:
        result = client.get_activities("ACC")

    assert result == [{"type": "Trades"}]
    assert get.call_count == 1
    params = get.call_args.kwargs["params"]
    start = datetime.fromisoformat(params["startTime"])
    end = datetime.fromisoformat(params["endTime"])
    assert timedelta(days=29, hours=23) <= end - start <= timedelta(days=30, hours=1)


def test_get_activities_chunks_long_range_and_concatenates(tmp_path):
    """A 75-day range fans out into 3 sequential calls and merges results."""
    token_path = tmp_path / "token.json"
    _seed_token_file(token_path)
    client = QuestradeClient(token_path=token_path)

    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=75)

    responses = [
        _mock_response(200, {"activities": [{"id": "chunk-1"}]}),
        _mock_response(200, {"activities": [{"id": "chunk-2-a"}, {"id": "chunk-2-b"}]}),
        _mock_response(200, {"activities": [{"id": "chunk-3"}]}),
    ]
    with patch(
        "questlit.questrade.requests.get", side_effect=responses
    ) as get:
        result = client.get_activities("ACC", start_time=start, end_time=end)

    assert get.call_count == 3
    assert [row["id"] for row in result] == ["chunk-1", "chunk-2-a", "chunk-2-b", "chunk-3"]

    # Chunks tile the range edge-to-edge with no gaps and no overlap.
    windows = [call.kwargs["params"] for call in get.call_args_list]
    assert windows[0]["startTime"] == start.isoformat()
    assert windows[-1]["endTime"] == end.isoformat()
    for prev, nxt in zip(windows, windows[1:]):
        assert prev["endTime"] == nxt["startTime"]


def test_chunk_date_range_helper():
    """Boundary cases: empty/equal range, exact-fit, larger-than-window."""
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)

    # Empty range yields nothing.
    assert list(_chunk_date_range(base, base)) == []

    # Range smaller than max_days yields a single chunk.
    chunks = list(_chunk_date_range(base, base + timedelta(days=10), max_days=30))
    assert chunks == [(base, base + timedelta(days=10))]

    # Range equal to max_days yields a single chunk.
    chunks = list(_chunk_date_range(base, base + timedelta(days=30), max_days=30))
    assert chunks == [(base, base + timedelta(days=30))]

    # Range > max_days yields multiple edge-to-edge chunks.
    chunks = list(_chunk_date_range(base, base + timedelta(days=65), max_days=30))
    assert len(chunks) == 3
    assert chunks[0] == (base, base + timedelta(days=30))
    assert chunks[1] == (base + timedelta(days=30), base + timedelta(days=60))
    assert chunks[2] == (base + timedelta(days=60), base + timedelta(days=65))


def test_get_balances_returns_full_payload(tmp_path):
    """get_balances returns the raw dict with all four sibling lists."""
    token_path = tmp_path / "token.json"
    _seed_token_file(token_path)
    client = QuestradeClient(token_path=token_path)

    balances_payload = {
        "perCurrencyBalances": [
            {"currency": "CAD", "cash": 100.0, "totalEquity": 200.0},
            {"currency": "USD", "cash": 50.0, "totalEquity": 75.0},
        ],
        "combinedBalances": [{"currency": "CAD", "cash": 165.0, "totalEquity": 290.0}],
        "sodPerCurrencyBalances": [{"currency": "CAD", "cash": 100.0}],
        "sodCombinedBalances": [{"currency": "CAD", "cash": 165.0}],
    }
    with patch(
        "questlit.questrade.requests.get",
        return_value=_mock_response(200, balances_payload),
    ) as get:
        result = client.get_balances("ACC")

    assert result == balances_payload
    called_url = get.call_args.args[0]
    assert called_url == "https://api01.iq.questrade.com/v1/accounts/ACC/balances"


def test_get_all_balances_tags_account_fields(tmp_path):
    """Each per-currency balance row carries its account number and type."""
    token_path = tmp_path / "token.json"
    _seed_token_file(token_path)
    client = QuestradeClient(token_path=token_path)

    responses = [
        _mock_response(200, {"accounts": [{"number": "A1", "type": "TFSA"}]}),
        _mock_response(
            200,
            {
                "perCurrencyBalances": [
                    {"currency": "CAD", "cash": 10.0, "totalEquity": 20.0},
                    {"currency": "USD", "cash": 5.0, "totalEquity": 15.0},
                ],
                "combinedBalances": [{"currency": "CAD", "cash": 16.5}],
                "sodPerCurrencyBalances": [],
                "sodCombinedBalances": [],
            },
        ),
    ]
    with patch("questlit.questrade.requests.get", side_effect=responses):
        rows = client.get_all_balances()

    assert rows == [
        {
            "accountNumber": "A1",
            "accountType": "TFSA",
            "currency": "CAD",
            "cash": 10.0,
            "totalEquity": 20.0,
        },
        {
            "accountNumber": "A1",
            "accountType": "TFSA",
            "currency": "USD",
            "cash": 5.0,
            "totalEquity": 15.0,
        },
    ]


def test_search_symbols_hits_correct_url(tmp_path):
    token_path = tmp_path / "token.json"
    _seed_token_file(token_path)
    client = QuestradeClient(token_path=token_path)

    payload = {"symbols": [{"symbol": "AAPL", "symbolId": 8049}]}
    with patch(
        "questlit.questrade.requests.get",
        return_value=_mock_response(200, payload),
    ) as get:
        result = client.search_symbols("AAPL")

    assert result == payload["symbols"]
    called_url = get.call_args.args[0]
    assert called_url == "https://api01.iq.questrade.com/v1/symbols/search"
    assert get.call_args.kwargs["params"] == {"prefix": "AAPL"}


def test_get_candles_resolves_symbol_then_fetches(tmp_path):
    token_path = tmp_path / "token.json"
    _seed_token_file(token_path)
    client = QuestradeClient(token_path=token_path)

    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 1, 5, tzinfo=timezone.utc)
    responses = [
        _mock_response(200, {"symbols": [{"symbol": "AAPL", "symbolId": 8049}]}),
        _mock_response(
            200,
            {"candles": [{"start": "2025-01-02", "open": 1.0, "close": 2.0}]},
        ),
    ]
    with patch(
        "questlit.questrade.requests.get", side_effect=responses
    ) as get:
        result = client.get_candles("AAPL", start, end, interval="OneDay")

    assert result == [{"start": "2025-01-02", "open": 1.0, "close": 2.0}]
    assert get.call_count == 2
    candles_url = get.call_args_list[1].args[0]
    assert candles_url == "https://api01.iq.questrade.com/v1/markets/candles/8049"
    candles_params = get.call_args_list[1].kwargs["params"]
    assert candles_params == {
        "startTime": "2025-01-01T00:00:00+00:00",
        "endTime": "2025-01-05T00:00:00+00:00",
        "interval": "OneDay",
    }


def test_get_candles_picks_exact_symbol_match(tmp_path):
    """Prefix search returns near-misses; only the exact match is used."""
    token_path = tmp_path / "token.json"
    _seed_token_file(token_path)
    client = QuestradeClient(token_path=token_path)

    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 1, 2, tzinfo=timezone.utc)
    responses = [
        _mock_response(
            200,
            {
                "symbols": [
                    {"symbol": "AAPL.MX", "symbolId": 1111},
                    {"symbol": "AAPL", "symbolId": 8049},
                    {"symbol": "AAPLW", "symbolId": 2222},
                ]
            },
        ),
        _mock_response(200, {"candles": []}),
    ]
    with patch(
        "questlit.questrade.requests.get", side_effect=responses
    ) as get:
        client.get_candles("AAPL", start, end)

    candles_url = get.call_args_list[1].args[0]
    assert candles_url.endswith("/v1/markets/candles/8049")


def test_get_candles_raises_on_no_match(tmp_path):
    token_path = tmp_path / "token.json"
    _seed_token_file(token_path)
    client = QuestradeClient(token_path=token_path)

    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 1, 2, tzinfo=timezone.utc)
    with patch(
        "questlit.questrade.requests.get",
        return_value=_mock_response(
            200, {"symbols": [{"symbol": "AAPL.MX", "symbolId": 1111}]}
        ),
    ):
        with pytest.raises(ValueError, match="No exact symbol match"):
            client.get_candles("AAPL", start, end)


def test_get_candles_rejects_invalid_interval(tmp_path):
    """Unknown interval raises before any HTTP call is made."""
    token_path = tmp_path / "token.json"
    _seed_token_file(token_path)
    client = QuestradeClient(token_path=token_path)

    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 1, 2, tzinfo=timezone.utc)
    with patch("questlit.questrade.requests.get") as get:
        with pytest.raises(ValueError, match="Unknown interval"):
            client.get_candles("AAPL", start, end, interval="NotAThing")
    get.assert_not_called()


def test_get_candles_chunks_long_range_for_short_interval(tmp_path):
    """OneMinute caps at 1 calendar day per chunk; 10 days → 10 calls."""
    token_path = tmp_path / "token.json"
    _seed_token_file(token_path)
    client = QuestradeClient(token_path=token_path)

    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=10)

    symbols_resp = _mock_response(
        200, {"symbols": [{"symbol": "AAPL", "symbolId": 8049}]}
    )
    candle_chunks = [
        _mock_response(200, {"candles": [{"id": f"chunk-{i}"}]}) for i in range(10)
    ]
    with patch(
        "questlit.questrade.requests.get",
        side_effect=[symbols_resp, *candle_chunks],
    ) as get:
        result = client.get_candles("AAPL", start, end, interval="OneMinute")

    # 1 symbol-search call + 10 candle chunks
    assert get.call_count == 11
    assert [row["id"] for row in result] == [f"chunk-{i}" for i in range(10)]

    candle_calls = get.call_args_list[1:]
    windows = [call.kwargs["params"] for call in candle_calls]
    assert windows[0]["startTime"] == start.isoformat()
    assert windows[-1]["endTime"] == end.isoformat()
    for prev, nxt in zip(windows, windows[1:]):
        assert prev["endTime"] == nxt["startTime"]
        assert prev["interval"] == "OneMinute"


def test_get_candles_attaches_utc_to_naive_datetimes(tmp_path):
    """Naive datetimes serialize as UTC in the candles request params."""
    token_path = tmp_path / "token.json"
    _seed_token_file(token_path)
    client = QuestradeClient(token_path=token_path)

    naive_start = datetime(2025, 1, 1)
    naive_end = datetime(2025, 1, 2)
    responses = [
        _mock_response(200, {"symbols": [{"symbol": "AAPL", "symbolId": 8049}]}),
        _mock_response(200, {"candles": []}),
    ]
    with patch(
        "questlit.questrade.requests.get", side_effect=responses
    ) as get:
        client.get_candles("AAPL", naive_start, naive_end)

    params = get.call_args_list[1].kwargs["params"]
    assert params["startTime"] == "2025-01-01T00:00:00+00:00"
    assert params["endTime"] == "2025-01-02T00:00:00+00:00"


def test_get_all_positions_tags_account_fields(tmp_path):
    token_path = tmp_path / "token.json"
    token_path.write_text(
        json.dumps(
            {
                "access_token": "access-abc",
                "refresh_token": "r",
                "api_server": "https://api01.iq.questrade.com/",
                "expires_at": time.time() + 1000,
            }
        )
    )
    client = QuestradeClient(token_path=token_path)

    responses = [
        _mock_response(200, {"accounts": [{"number": "A1", "type": "TFSA"}]}),
        _mock_response(200, {"positions": [{"symbol": "AAPL", "openQuantity": 5}]}),
    ]
    with patch("questlit.questrade.requests.get", side_effect=responses):
        rows = client.get_all_positions()

    assert rows == [
        {
            "accountNumber": "A1",
            "accountType": "TFSA",
            "symbol": "AAPL",
            "openQuantity": 5,
        }
    ]
