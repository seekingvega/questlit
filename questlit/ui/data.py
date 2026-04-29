"""Streamlit-cached loaders backed by ``QuestradeClient``.

Each loader is wrapped in ``@st.cache_data`` so repeated reruns within a TTL
window do not re-hit the Questrade API. Pages should import from this module
rather than instantiating ``QuestradeClient`` directly.
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from questlit.questrade import QuestradeClient


@st.cache_data(ttl="1d")
def load_accounts(_seed: str | None = None) -> list[dict]:
    """Return the authenticated user's Questrade accounts.

    ``_seed`` is only consumed on first auth (or after the cached refresh
    token has been rejected). It is named with a leading underscore so
    Streamlit excludes it from the cache key — the same accounts list is
    returned regardless of which seed bootstrapped the session.
    """
    return QuestradeClient(seed_refresh_token=_seed).get_accounts()


@st.cache_data(ttl=60)
def load_positions(_seed: str | None = None) -> list[dict]:
    return QuestradeClient(seed_refresh_token=_seed).get_all_positions()


@st.cache_data(ttl=60)
def load_balances() -> list[dict]:
    return QuestradeClient().get_all_balances()


@st.cache_data(ttl=60)
def load_orders(
    account_id: str | int, start_time: datetime | None = None
) -> list[dict]:
    return QuestradeClient().get_orders(
        account_id, start_time=start_time, state_filter="All"
    )


@st.cache_data(ttl=60)
def load_activities(
    account_id: str | int, start_time: datetime, end_time: datetime
) -> list[dict]:
    return QuestradeClient().get_activities(
        account_id, start_time=start_time, end_time=end_time
    )
