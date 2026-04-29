"""Tests for questlit.questrade.

HTTP is mocked at the ``requests.post`` / ``requests.get`` boundary so the
tests are hermetic. ``tmp_path`` isolates each test's token file.
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from questlit.questrade import QuestradeAuthError, QuestradeClient


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
