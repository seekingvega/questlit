"""Candles page: OHLCV chart for a single symbol via Plotly."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from questlit.ui.data import (
    load_activities,
    load_candles,
    load_orders,
    load_symbol_info,
)

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


_ORDER_SIDE_COLOR = {"Buy": "green", "Sell": "red"}


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
        if order_type == "Limit":
            price, dash = o.get("limitPrice"), "solid"
        elif order_type in ("Stop", "StopLimit"):
            price, dash = o.get("stopPrice"), "dash"
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

    styles = {
        "Buy": dict(symbol="triangle-up", color="blue", size=8, opacity=0.9),
        "Sell": dict(symbol="triangle-down", color="orange", size=8, opacity=0.9),
        "Dividend": dict(symbol="diamond", color="purple", size=8, opacity=0.9),
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


def main() -> None:
    st.set_page_config(layout="wide", initial_sidebar_state="collapsed")

    # account selection
    accounts = st.session_state["accounts"]
    acc_dict = {f"{a['number']} ({a['type']})": a["number"] for a in accounts}
    with st.sidebar:
        select_acc = st.selectbox(
            "Account",
            help="select an account to view past trades for your Symbol",
            options=[""] + list(acc_dict.keys()),
        )
        target_acc = acc_dict[select_acc] if select_acc else None

    # candles data input
    cols = st.columns([2, 2, 1, 2, 2])
    symbol = cols[0].text_input("Symbol", value="AAPL").strip().upper()
    interval = cols[1].selectbox("Interval", _INTERVALS, index=3)
    range_str = cols[2].text_input("Range", value="6m")
    end = cols[3].date_input("End", value=pd.Timestamp.now().date())

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
    open_orders = [o for o in orders if o.get("state") != "Executed"]
    executed_orders = [o for o in orders if o.get("state") == "Executed"]
    plot_orders(fig, open_orders)
    plot_activities(
        fig,
        [_executed_order_to_activity(o) for o in executed_orders] + activities,
        df,
    )
    fig.update_layout(
        title=title,
        height=700,
        margin=dict(l=10, r=10, t=50, b=10),
        xaxis_rangeslider_visible=False,
    )
    st.plotly_chart(fig, use_container_width=True)


main()
