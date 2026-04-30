"""Candles page: OHLCV chart for a single symbol via Plotly."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from questlit.ui.data import load_candles

_INTERVALS = ["OneMinute", "FiveMinutes", "OneHour", "OneDay", "OneWeek"]


def main() -> None:
    cols = st.columns([2, 2, 2, 2])
    symbol = cols[0].text_input("Symbol", value="AAPL").strip().upper()
    interval = cols[1].selectbox("Interval", _INTERVALS, index=3)
    end = cols[2].date_input("End", value=pd.Timestamp.now().date())
    start = cols[3].date_input(
        "Start", value=pd.Timestamp.now().date() - pd.Timedelta(days=90)
    )

    if not symbol:
        st.info("Enter a ticker symbol to load candles.")
        return

    try:
        candles = load_candles(
            symbol,
            start_time=pd.Timestamp(start),
            end_time=pd.Timestamp(end) + pd.Timedelta(days=1),
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
        height=600,
        margin=dict(l=10, r=10, t=30, b=10),
        xaxis_rangeslider_visible=False,
    )
    st.plotly_chart(fig, use_container_width=True)


main()
