"""Candles page: OHLCV chart for a single symbol via Plotly."""

from __future__ import annotations

import re
from cmath import e
from datetime import datetime, timedelta
from urllib.parse import urlencode

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots
from streamlit_shortcuts import add_shortcuts

from questlit.ui.charting import (
    add_ATR_trace,
    add_MACD_trace,
    add_RSI_trace,
    add_volume_profile,
    plot_moving_averages,
)
from questlit.ui.data import (
    load_activities,
    load_candles,
    load_orders,
    load_symbol_info,
)
from questlit.ui.ta_utils import add_ATR, add_MACD, add_moving_average, add_RSI

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


def _parse_ema_periods(s: str) -> list[int]:
    """Parse a comma-separated EMA periods string into positive ints.

    Whitespace and empty fragments are ignored. Non-integer fragments are
    silently skipped so a partially-typed input doesn't raise.

    Examples:
        >>> _parse_ema_periods("22, 11")
        [22, 11]
        >>> _parse_ema_periods("")
        []
        >>> _parse_ema_periods("9,,bogus, 21 ")
        [9, 21]
    """
    out: list[int] = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            n = int(part)
        except ValueError:
            continue
        if n > 0:
            out.append(n)
    return out


def _get_activiies(target_acc, symbol, start_time, end_time):
    activities = load_activities(target_acc, start_time=start_time, end_time=end_time)
    activities = (
        [
            a
            for a in activities
            if a["symbol"] == symbol.upper() and a["type"] in ["Trades", "Dividends"]
        ]
        if activities
        else []
    )
    return activities


def _get_orders(target_acc, symbol, start_time, end_time):
    sym = symbol.upper()
    all_orders = (
        load_orders(
            target_acc,
            start_time=start_time,
            end_time=end_time,
            state_filter="All",  # "Open"
        )
        or []
    )
    open_orders = [
        o
        for o in all_orders
        if o["symbol"] == sym and o["state"] in ("Accepted", "ContingentOrder")
    ]
    closed_orders = [  # today's closed orders show up here instead of in activities
        o
        for o in all_orders
        if o["symbol"] == sym
        and o["state"] in ("Executed")
        and pd.to_datetime(o["updateTime"]).date()
        == datetime.now().date()  # pd.Timestamp(end_time).date()
    ]

    # Closed orders executed on end_time's date
    # end_date = pd.Timestamp(end_time).date()
    # day_start = pd.Timestamp(end_date - timedelta(days=1))
    # closed_orders = (
    #     load_orders(
    #         target_acc, start_time=start_time, end_time=end_time, state_filter="Closed"
    #     )
    #     or []
    # )
    # closed_orders = [
    #     o
    #     for o in closed_orders
    #     # if o["symbol"] == sym
    #     # and o["state"] == "Executed"
    #     # and pd.to_datetime(o["updateTime"]).date() == end_date
    # ]
    # print(f"{len(closed_orders)} closedn orders found.")
    return open_orders + closed_orders


def _executed_order_to_activity(order: dict) -> dict:
    """Reshape an executed Questrade order into an activity-shaped dict.

    Lets executed orders ride through ``plot_activities`` as Buy/Sell markers
    without modifying that function. Buys are signed negative on
    ``netAmount`` (cash out) and Sells positive (cash in), matching how the
    Questrade activities feed signs trade ``netAmount`` values.

    Args:
        order: A Questrade order dict (must have ``state == "Executed"``).

    Returns:
        An activity-shaped dict consumed by ``plot_activities``.

    Examples:
        >>> o = {"side": "Buy", "symbol": "AAPL", "state": "Executed",
        ...      "filledQuantity": 10, "avgExecPrice": 150.0,
        ...      "updateTime": "2026-05-01T15:30:00-04:00"}
        >>> a = _executed_order_to_activity(o)
        >>> a["type"], a["action"], a["symbol"], a["quantity"], a["price"]
        ('Trades', 'Buy', 'AAPL', 10, 150.0)
        >>> a["netAmount"]
        -1500.0
        >>> _executed_order_to_activity({"side": "Sell", "filledQuantity": 5,
        ...     "avgExecPrice": 20.0})["netAmount"]
        100.0
    """
    qty = order.get("filledQuantity") or order.get("totalQuantity") or 0
    price = order.get("avgExecPrice") or order.get("limitPrice") or 0.0
    sign = -1 if order.get("side") == "Buy" else 1
    return {
        "type": "Trades",
        "action": order.get("side", ""),
        "tradeDate": order.get("updateTime"),
        "symbol": order.get("symbol", ""),
        "quantity": qty,
        "price": price,
        "netAmount": sign * qty * price,
    }


_ORDER_SIDE_COLOR = {"Buy": "DodgerBlue", "Sell": "DeepPink"}
# css color names: https://www.w3schools.com/cssref/css_colors.php


def plot_orders(fig, orders):
    """Overlay open orders as horizontal price lines on the candle subplot.

    Limit orders render as a solid line at ``limitPrice``; Stop and StopLimit
    render as a dashed line at ``stopPrice`` (the trigger). Color is green for
    Buy, red for Sell. Orders without a chartable price (Market, trailing
    stops) are skipped.

    Args:
        fig: A ``plotly.graph_objects.Figure`` whose row=1 is the candlestick.
        orders: List of Questrade order dicts (already filtered by symbol).

    Returns:
        The figure, mutated in place and returned for chaining.
    """
    if not orders:
        return fig
    for o in orders:
        order_type = o.get("orderType", "")
        if (
            order_type == "Limit"
        ):  # dash options include 'dash', 'dot', 'dashdot' and 'solid'
            price, dash = o.get("limitPrice"), "dash"
        elif order_type in ("Stop", "StopLimit"):
            price, dash = o.get("stopPrice"), "dot"
        else:
            continue
        if price is None:
            continue

        side = o.get("side", "")
        color = _ORDER_SIDE_COLOR.get(side, "gray")
        qty = o.get("totalQuantity", "?")
        label = f"{side.upper()} {qty} ({order_type}) @ ${price:.2f}"
        if order_type == "StopLimit" and o.get("limitPrice") is not None:
            label += f" (limit price: ${o['limitPrice']:.2f})"

        fig.add_hline(
            y=price,
            line=dict(color=color, dash=dash, width=1),
            opacity=0.6,
            layer="below",
            annotation_text=label,
            annotation_position="top right",
            annotation_font=dict(color=color, size=10),
            annotation_opacity=0.6,
            row=1,
            col=1,
        )
    return fig


def plot_activities(fig, activities, df):
    """Overlay trade fills and dividends as markers on the candle subplot.

    Buys render as green up-triangles, sells as orange down-triangles, anchored
    at ``(tradeDate, price)``. Dividends render as purple diamonds at the
    candle low for the trade date (or the chart's min low if no candle aligns)
    since dividends have no execution price. Each category is grouped into a
    single trace so the legend stays compact.

    Args:
        fig: A ``plotly.graph_objects.Figure`` whose row=1 is the candlestick.
        activities: List of Questrade activity dicts (already filtered by
            symbol and ``type in {"Trades", "Dividends"}``).
        df: The candles dataframe, used to anchor dividend markers to a
            sensible y-coordinate (the candle low for that date).

    Returns:
        The figure, mutated in place and returned for chaining.
    """
    if not activities:
        return fig

    chart_low = float(df["low"].min())
    low_by_date: dict = {}
    for ts, low in zip(df["start"], df["low"]):
        if pd.notna(ts):
            low_by_date.setdefault(pd.Timestamp(ts).date(), float(low))

    def _div_y(date: pd.Timestamp) -> float:
        if pd.isna(date):
            return chart_low
        return low_by_date.get(pd.Timestamp(date).date(), chart_low)

    buckets: dict[str, dict[str, list]] = {
        "Buy": {"x": [], "y": [], "text": []},
        "Sell": {"x": [], "y": [], "text": []},
        "Dividend": {"x": [], "y": [], "text": []},
    }
    for a in activities:
        date = pd.to_datetime(a.get("tradeDate"))
        date_str = date.strftime("%Y-%m-%d") if pd.notna(date) else "?"
        symbol = a.get("symbol", "")
        qty = a.get("quantity", 0)
        price = a.get("price") or 0.0
        net = a.get("netAmount", 0.0)
        if a.get("type") == "Dividends":
            buckets["Dividend"]["x"].append(date)
            buckets["Dividend"]["y"].append(_div_y(date))
            buckets["Dividend"]["text"].append(
                f"{date_str} DIVIDEND {symbol} net ${net:,.2f}"
            )
            continue
        action = a.get("action", "")
        if action not in ("Buy", "Sell"):
            continue
        buckets[action]["x"].append(date)
        buckets[action]["y"].append(price)
        buckets[action]["text"].append(
            f"{date_str} {action.upper()} {qty} {symbol} @ ${price:.2f} (net ${net:,.2f})"
        )

    # css color names: https://www.w3schools.com/cssref/css_colors.php
    styles = {
        "Buy": dict(symbol="triangle-up", color="DodgerBlue", size=10, opacity=0.6),
        "Sell": dict(symbol="triangle-down", color="DeepPink", size=10, opacity=0.6),
        "Dividend": dict(symbol="diamond", color="Gold", size=8, opacity=0.6),
    }
    for name, data in buckets.items():
        if not data["x"]:
            continue
        fig.add_trace(
            go.Scatter(
                x=data["x"],
                y=data["y"],
                mode="markers",
                marker=styles[name],
                name=name,
                hovertext=data["text"],
                hoverinfo="text",
            ),
            row=1,
            col=1,
        )
    return fig


def plot_ohlc(
    df: pd.DataFrame, title: str, symbol: str, rsi_hi: int = 70, rsi_lo: int = 30
):
    has_macd = all(c in df.columns for c in ("MACD", "MACD_signal", "MACD_histogram"))
    has_rsi = "RSI" in df.columns
    has_atr = "ATR" in df.columns

    n_extra = sum([has_macd, has_rsi, has_atr])
    total_rows = 2 + n_extra
    if total_rows == 2:
        row_heights, height = [0.75, 0.25], 700
    elif total_rows == 3:
        row_heights, height = [0.6, 0.2, 0.2], 900
    elif total_rows == 4:
        row_heights, height = [0.5, 0.18, 0.16, 0.16], 1050
    else:  # 5 rows
        row_heights, height = [0.44, 0.16, 0.14, 0.13, 0.13], 1200

    fig = make_subplots(
        rows=total_rows,
        cols=1,
        shared_xaxes=True,
        row_heights=row_heights,
        vertical_spacing=0.03,
    )
    plot_moving_averages(
        fig, df
    )  # plotting averages first to make sure candles are in front
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
        go.Bar(
            x=df["start"],
            y=df["volume"],
            name="Volume",
            showlegend=False,
            marker_color="MediumPurple",  # "#636efa",
        ),
        row=2,
        col=1,
    )
    next_row = 3
    if has_macd:
        add_MACD_trace(
            fig, df, ref_row=next_row, date_col="start", draw_signal_line=True
        )
        fig.update_yaxes(title_text="MACD", row=next_row, col=1)
        next_row += 1
    if has_rsi:
        add_RSI_trace(fig, df, ref_row=next_row, date_col="start", hi=rsi_hi, lo=rsi_lo)
        fig.update_yaxes(title_text="RSI", row=next_row, col=1, range=[0, 100])
        next_row += 1
    if has_atr:
        add_ATR_trace(fig, df, ref_row=next_row, date_col="start")
        fig.update_yaxes(title_text="ATR", row=next_row, col=1)
        next_row += 1
    fig.update_layout(
        title=title,
        height=height,
        margin=dict(l=10, r=10, t=50, b=10),
        xaxis_rangeslider_visible=False,
    )
    return fig


def get_st_app_url(qp: dict = st.query_params.to_dict()):
    qs = urlencode(qp, doseq=True)
    base = st.context.url.split("?")[0].split("#")[0]
    return f"{base}?{qs}" if qs else base


def main() -> None:
    st.set_page_config(layout="wide", initial_sidebar_state="collapsed")

    # account selection
    accounts = st.session_state["accounts"]
    acc_dict = {f"{a['number']}-{a['type']}": a["number"] for a in accounts}
    with st.sidebar:
        select_acc = st.selectbox(
            "Account",
            help="select an account to view past trades for your Symbol",
            options=[""] + list(acc_dict.keys()),
            key="account",
            bind="query-params",
        )
        target_acc = acc_dict[select_acc] if select_acc else None
        charting_cofig_container = st.expander(f"Charting", icon=":material/settings:")

    # candles data input
    cols = st.columns([2, 2, 1, 2, 2])
    symbol = (
        cols[0]
        .text_input(
            "Symbol",
            value="AAPL",
            key="symbol",
            bind="query-params",
            placeholder="cmd+/",
        )
        .strip()
        .upper()
    )
    interval = cols[1].selectbox(
        "Interval", _INTERVALS, index=3, key="interval", bind="query-params"
    )
    range_str = cols[2].text_input(
        "Range", value="6m", key="range", bind="query-params"
    )
    end = cols[3].date_input(
        "End", value=pd.Timestamp.now().date(), key="end", bind="query-params"
    )

    end_ts = pd.Timestamp(end, hour=23, minute=59, second=59)
    start_ts = _parse_range(range_str, end_ts)
    if start_ts is None:
        cols[4].date_input("Start", value=end, disabled=True)
        st.error(
            f"Cannot parse range {range_str!r}. "
            "Use formats like '7d', '2w', '6m', '1y'."
        )
        return

    cols[4].date_input("Start", value=start_ts.date(), disabled=True)

    # charting configs
    with charting_cofig_container:
        tab_ma, tab_vol, tab_macd, tab_others = st.tabs(
            ["Averages", "Volume", "MACD", ":material/more:"]
        )
        with tab_ma:
            cols = st.columns(2)
            ma_type = cols[0].selectbox("Average Type", options=["EMA", "SMA", "VWAP"])
            ma_durations = cols[1].text_input(
                "periods", value="11,22", help="comma separated"
            )
        with tab_vol:
            do_volume_profile = st.toggle("Volume Profile", value=False)
            if do_volume_profile:
                vol_interval = st.selectbox(
                    "Volume Profile Interval",
                    options=[
                        "OneDay",
                        "FourHours",
                        "TwoHours",
                        "OneHour",
                        "HalfHour",
                    ],
                    index=0,
                    help=(
                        "you can use more gradular interval to compute volume profile\n\n"
                        "but note that only `FourHours` and `TwoHours` have tested to work"
                        "and you would have about 3-month of data."
                    ),
                )
        with tab_macd:
            do_macd = st.toggle("MACD", value=True)
            if do_macd:
                macd_cols = st.columns(3)
                macd_fast = macd_cols[0].number_input(
                    "fast", value=12, min_value=1, step=1
                )
                macd_slow = macd_cols[1].number_input(
                    "slow", value=26, min_value=1, step=1
                )
                macd_signal = macd_cols[2].number_input(
                    "signal", value=9, min_value=1, step=1
                )
        with tab_others:
            do_rsi = st.toggle("RSI", value=False)
            rsi_period, rsi_hi, rsi_lo = 14, 70, 30
            if do_rsi:
                rsi_cols = st.columns(3)
                rsi_period = rsi_cols[0].number_input(
                    "RSI period", value=14, min_value=2, step=1
                )
                rsi_hi = rsi_cols[1].number_input(
                    "hi", value=70, min_value=1, max_value=100, step=1
                )
                rsi_lo = rsi_cols[2].number_input(
                    "lo", value=30, min_value=0, max_value=99, step=1
                )

            cols = st.columns(2)
            do_atr = cols[0].toggle("ATR", value=True)
            if do_atr:
                atr_use_ema = cols[1].toggle(
                    "use EMA", value=True, help="use EMA to average True Range?"
                )
                atr_period = st.number_input(
                    "period", value=13, min_value=2, step=1, help="ATR period"
                )

    # Keyboard shortcuts
    add_shortcuts(symbol="cmd+/")

    # show monthly chart url if on daily chart
    if interval in ["OneDay"]:
        qp = st.query_params.to_dict()
        qp["interval"] = "OneWeek"
        qp["range"] = "2y"
        app_url = get_st_app_url(qp)
        st.sidebar.caption(f"Open [Weekly Chart]({app_url}) for {symbol}")

    if not symbol:
        st.info("Enter a ticker symbol to load candles.")
        return
    else:
        # let's load orders with start_ts and end_ts
        orders = (
            _get_orders(target_acc, symbol, start_time=start_ts, end_time=end_ts)
            if target_acc
            else []
        )
        activities = (
            _get_activiies(target_acc, symbol, start_time=start_ts, end_time=end_ts)
            if target_acc
            else []
        )

        if target_acc:
            st.sidebar.info(
                f"{len(orders)} orders and {len(activities)} activities found for account `{target_acc}` within the date range for `{symbol}`"
            )
            tab_ord, tab_act = st.sidebar.tabs(["orders", "activities"])
            if orders:
                tab_ord.dataframe(pd.DataFrame(orders))
            if activities:
                tab_act.dataframe(pd.DataFrame(activities))

    try:
        # we actually need couple extra days before for technical indicators that does averaging, e.g. EMA
        candle_start_ts = start_ts - timedelta(weeks=15)
        candles = load_candles(
            symbol,
            start_time=candle_start_ts,  # start_ts,
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
    df["start"] = (
        pd.to_datetime(df["start"], utc=True)
        .dt.tz_convert("America/New_York")
        .dt.tz_localize(None)
    )  # parse as UTC (handles mixed DST offsets), shift to ET wall-clock, then drop tz to compare against naive start_ts
    # Compute EMAs on the full warm-up window first, then slice to the visible
    # range — otherwise early bars in view would have NaN/noisy EMA values.
    ma_periods = _parse_ema_periods(ma_durations)
    for period in ma_periods:
        add_moving_average(
            df, period, type=ma_type.lower(), price_col="close", vol_col="volume"
        )
    if do_macd:
        add_MACD(
            df,
            fast=int(macd_fast),
            slow=int(macd_slow),
            signal=int(macd_signal),
            price_col="close",
        )
    if do_rsi:
        add_RSI(df, n=int(rsi_period), price_col="close")
    if do_atr:
        add_ATR(
            df,
            period=int(atr_period),
            use_ema=atr_use_ema,
            high_col="high",
            low_col="low",
            close_col="close",
            channel_dict=None,
            return_TR=False,
        )

    # remove warm-up window
    df = df[df["start"] > pd.Timestamp(start_ts)]

    # Create OHLC Chart
    info = load_symbol_info(symbol) or {}
    desc = info.get("description") or symbol
    exch = info.get("listingExchange")
    title = f"{desc} ({exch})" if exch else desc
    fig = plot_ohlc(
        df, title=title, symbol=symbol, rsi_hi=int(rsi_hi), rsi_lo=int(rsi_lo)
    )

    # Additional overlay to chart
    open_orders = [o for o in orders if o.get("state") != "Executed"]
    executed_orders = [o for o in orders if o.get("state") == "Executed"]
    plot_orders(fig, open_orders)
    plot_activities(
        fig,
        [_executed_order_to_activity(o) for o in executed_orders] + activities,
        df,
    )
    if do_volume_profile:
        v_candles = load_candles(
            symbol,
            start_time=start_ts,
            end_time=end_ts + pd.Timedelta(days=1),
            interval=vol_interval,
        )
        if not v_candles:
            st.info(f"No candles returned for {symbol} in {vol_interval}.")
        else:
            _df = pd.DataFrame(v_candles)
            _df["start"] = pd.to_datetime(_df["start"])
            fig = add_volume_profile(fig, _df)
            start_date = _df["start"].min().date()
            months = (_df["start"].max() - _df["start"].min()).days / 30.44
            tab_vol.info(
                f"{months:.0f} months of volume data (available since {start_date})"
            )

    st.plotly_chart(fig, width="stretch")


main()
