"""Candles page: OHLCV chart for a single symbol via Plotly."""

from __future__ import annotations

import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from questlit.ui.data import load_candles, load_symbol_info

_INTERVALS = ["OneMinute", "FiveMinutes", "OneHour", "OneDay", "OneWeek"]
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


def main() -> None:
    cols = st.columns([2, 2, 1, 2, 2])
    symbol = cols[0].text_input("Symbol", value="AAPL").strip().upper()
    interval = cols[1].selectbox("Interval", _INTERVALS, index=3)
    range_str = cols[2].text_input("Range", value="3m")
    end = cols[3].date_input("End", value=pd.Timestamp.now().date())

    end_ts = pd.Timestamp(end)
    start_ts = _parse_range(range_str, end_ts)
    if start_ts is None:
        cols[4].date_input("Start", value=end, disabled=True)
        st.error(
            f"Cannot parse range {range_str!r}. "
            "Use formats like '7d', '2w', '6m', '1y'."
        )
        return

    cols[4].date_input("Start", value=start_ts.date(), disabled=True)

    if not symbol:
        st.info("Enter a ticker symbol to load candles.")
        return

    try:
        candles = load_candles(
            symbol,
            start_time=start_ts,
            end_time=end_ts + pd.Timedelta(days=1),
            interval=interval,
        )
    except ValueError as exc:
        st.error(str(exc))
        return

    if not candles:
        st.info(f"No candles returned for {symbol} in this range.")
        return

    df = pd.DataFrame(candles)
    df["start"] = pd.to_datetime(df["start"])

    info = load_symbol_info(symbol) or {}
    desc = info.get("description") or symbol
    exch = info.get("listingExchange")
    title = f"{desc} ({exch})" if exch else desc

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.75, 0.25],
        vertical_spacing=0.03,
    )
    fig.add_trace(
        go.Candlestick(
            x=df["start"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name=symbol,
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(x=df["start"], y=df["volume"], name="Volume", showlegend=False),
        row=2,
        col=1,
    )
    fig.update_layout(
        title=title,
        height=700,
        margin=dict(l=10, r=10, t=50, b=10),
        xaxis_rangeslider_visible=False,
    )
    st.plotly_chart(fig, use_container_width=True)


main()
