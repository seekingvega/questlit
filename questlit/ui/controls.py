"""Shared Streamlit sidebar controls and page-independent helpers.

Houses utilities reused across pages so the ``questlit.ui`` layer never has to
import from a ``pages/*`` module:

- ``_parse_range`` / ``get_st_app_url`` — pure helpers (relocated here from
  ``pages/candles.py``).
- ``account_dates_sidebar`` — the Account / Balance / Dates sidebar block shared
  by the positions and closed-trades pages.
"""

from __future__ import annotations

import re
from urllib.parse import urlencode

import pandas as pd
import streamlit as st

from questlit.ui.data import load_balances
from questlit.ui.formatting import currency_column_config

_RANGE_PATTERN = re.compile(r"^\s*(\d+)\s*([dwmy])\s*$", re.IGNORECASE)


def _parse_range(s: str, end: pd.Timestamp) -> pd.Timestamp | None:
    """Subtract a relative range string from ``end`` to get a start timestamp.

    Accepts ``Nd`` (days), ``Nw`` (weeks), ``Nm`` (months), ``Ny`` (years),
    case-insensitive. Months and years use ``pd.DateOffset`` so they're
    calendar-aware. Returns ``None`` on parse failure.

    Examples:
        >>> e = pd.Timestamp("2026-04-30")
        >>> _parse_range("3m", e)
        Timestamp('2026-01-30 00:00:00')
        >>> _parse_range("10d", e)
        Timestamp('2026-04-20 00:00:00')
        >>> _parse_range("bogus", e) is None
        True
    """
    m = _RANGE_PATTERN.match(s)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit == "d":
        return end - pd.Timedelta(days=n)
    if unit == "w":
        return end - pd.Timedelta(weeks=n)
    if unit == "m":
        return end - pd.DateOffset(months=n)
    return end - pd.DateOffset(years=n)


def get_st_app_url(qp: dict = st.query_params.to_dict()):
    """Build a URL for the current page with ``qp`` as the query string."""
    qs = urlencode(qp, doseq=True)
    base = st.context.url.split("?")[0].split("#")[0]
    return f"{base}?{qs}" if qs else base


def tv_url(symbol: str) -> str:
    symbol = symbol.upper()
    if symbol.endswith((".TO", ".VN")):
        if symbol.endswith(".TO"):
            return (
                f"https://www.tradingview.com/symbols/TSX-{symbol.replace('.TO','')}/"
            )
        else:
            return (
                f"https://www.tradingview.com/symbols/TSXV-{symbol.replace('.VN','')}/"
            )
    else:
        return None


def account_dates_sidebar() -> tuple[str, pd.Timestamp, pd.Timestamp]:
    """Render the Account / Balance / Dates sidebar shared across pages.

    Reads ``accounts`` / ``accounts_dict`` from ``st.session_state`` (populated by
    ``ensure_authenticated``), renders the account selectbox, an Accounts and a
    Balance expander, and a Dates expander (End + Range → computed Start). Uses
    ``bind="query-params"`` so the ``account`` / ``end`` / ``range`` selections are
    shared across pages via the URL.

    Returns:
        ``(target_acc, start_ts, end_ts)`` where ``end_ts`` is the end-of-day after
        the selected End date and ``start_ts = end_ts - range``.

    Calls ``st.stop()`` if no account is selected or the Range string can't be
    parsed.
    """
    accounts = st.session_state["accounts"]
    acc_dict = st.session_state["accounts_dict"]
    with st.sidebar:
        target_acc = st.selectbox(
            "Account",
            help="select an account to view past trades for your Symbol",
            options=[""] + list(acc_dict.keys()),
            format_func=lambda x: f"{x}-{acc_dict[x]}" if x else "",
            key="account",
            bind="query-params",
        )
        info_container = st.expander("Accounts")
    info_container.dataframe(pd.DataFrame(accounts), hide_index=True)

    if not target_acc:
        st.warning("please select an account to continue :point_left:")
        st.stop()

    # Show Balance
    balance_container = st.sidebar.expander("Balance")
    with balance_container:
        balance = load_balances(target_acc)["perCurrencyBalances"]
        df_b = pd.DataFrame(balance)
        balance_container.dataframe(
            df_b, hide_index=True, column_config=currency_column_config(df_b)
        )

    # Dates Setup
    dates_container = st.sidebar.expander("Dates", expanded=True)
    with dates_container:
        end = st.date_input(
            "End",
            value=pd.Timestamp.now().date(),
            key="end",
            bind="query-params",
            max_value=pd.Timestamp.now().date(),
        )
        range_str = st.text_input(
            "Range",
            value="1y",
            key="range",
            bind="query-params",
            help="date range is used to search for orders and activities history for positions held",
        )
        end_ts = pd.Timestamp(end, hour=23, minute=59, second=59) + pd.Timedelta(days=1)
        start_ts = _parse_range(range_str, end_ts)
        if start_ts is None:
            st.date_input("Start", value=end, disabled=True)
            st.error(
                f"Cannot parse range {range_str!r}. "
                "Use formats like '7d', '2w', '6m', '1y'."
            )
            st.stop()

        st.date_input("Start", value=start_ts.date(), disabled=True)

    return target_acc, start_ts, end_ts
