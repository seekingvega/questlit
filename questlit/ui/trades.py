"""Reusable trade-analysis helpers shared across pages.

These functions are kept out of any ``pages/*`` module so they can be imported
without triggering a page's top-level ``main()`` render. Both the positions and
closed-trades pages render trade deep-dives via :func:`show_activities` and
classify closed round-trips via :func:`closed_trade_pnl` /
:func:`summarize_closed_trades`.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import streamlit as st
from millify import prettify

from questlit.ui.controls import get_st_app_url


def show_activities(
    symbol: str, df_pos: pd.DataFrame, df_activities: pd.DataFrame, st_container=None
):
    """show buys, sells (PnL), days-in position, dividends collected"""
    df_pos = df_pos[df_pos["symbol"] == symbol]
    is_open = len(df_pos) > 0
    if is_open:
        assert (
            len(df_pos) == 1
        ), f"Expected 1 open position for {symbol}, got {len(df_pos)}"
        pos_dict = df_pos.to_dict(orient="records")[0] if is_open else {}

    # organize df_activities
    _dfa = df_activities[df_activities["symbol"] == symbol]
    df_buys = _dfa[_dfa["action"] == "Buy"]
    df_sells = _dfa[_dfa["action"] == "Sell"]
    df_divs = _dfa[_dfa["type"] == "Dividends"]
    days = (
        pos_dict["days_invested"]
        if is_open
        else (
            pd.to_datetime(df_sells["tradeDate"].max())
            - pd.to_datetime(df_buys["tradeDate"].min())
        ).days
    )
    qty = pos_dict["openQuantity"] if is_open else df_buys["quantity"].sum()
    close_qty = qty if is_open else -df_sells["quantity"].sum()
    if close_qty != qty or qty == 0 or days <= 0:
        if st_container:
            st_container.warning(
                f"{symbol}: close quantity {close_qty} doesn't match open quantity {qty} or days invested ({days}) must be positive; Try increasing Date Range to get missing trades & activities."
            )
            return
        else:
            raise ValueError(
                f"close quantity {close_qty} doesn't match open quantity {qty}"
            )

    avg_cost = (
        pos_dict["averageEntryPrice"] * pos_dict["openQuantity"]
        if is_open
        else (df_buys["price"] * df_buys["quantity"]).sum()
    )
    last_value = (
        pos_dict["currentPrice"] * pos_dict["openQuantity"]
        if is_open
        else (df_sells["price"] * df_sells["quantity"]).sum() * -1
    )
    div_paid = df_divs["netAmount"].sum()
    div_yield = np.log1p(div_paid / avg_cost) / (days / 365)
    pnl = last_value - avg_cost + div_paid
    avg_price = avg_cost / (
        pos_dict["openQuantity"] if is_open else df_buys["quantity"].sum()
    )
    last_price = last_value / (
        pos_dict["openQuantity"] if is_open else -df_sells["quantity"].sum()
    )
    last_date = None if is_open else pd.to_datetime(df_sells["tradeDate"].max()).date()

    # getting candle url: swap the current page slug (between the last "/" and
    # "?") for "candles" so this works from any page, not just positions
    candle_qp = st.query_params.to_dict() | {"symbol": symbol}
    if last_date:
        candle_qp["end"] = last_date + timedelta(days=1)
    else:
        candle_qp.pop("end", None)
    base, sep, query = get_st_app_url(qp=candle_qp).partition("?")
    candle_url = f"{base.rsplit('/', 1)[0]}/candles{sep}{query}"

    tab_dash, tab_trades, tab_divs = st_container.tabs(
        ["Overview", "Trades", "Dividends"]
    )

    with tab_dash:
        cols = st.columns(4)

        l_metrics = [
            {
                "label": "symbol",
                "value": f"[{symbol}]({candle_url})",
                "delta": f"{qty} shares",
                "delta_color": "off",
                "delta_arrow": "off",
            },
            {"label": "Average Price", "value": prettify(f"{avg_price:.2f}")},
            {
                "label": "Last Price",
                "value": prettify(f"{last_price:.2f}"),
                "delta": f"{pnl/avg_cost:.1%}",
                "help": f"total return (including div): {pnl/avg_cost:.1%}",
            },
            {
                "label": "$ Dividend Paid",
                "value": prettify(f"{div_paid:.1f}"),
                "delta": f"{div_yield:.1%}",
                "help": f"div yield: {div_yield:.1%}",
            },
            {
                "label": "days invested",
                "value": days,
                "delta": "open" if is_open else "closed",
                "delta_color": "green" if is_open else "gray",
                "delta_arrow": "off",
                "help": "only reflects open quantity" if is_open else "",
            },
            {"label": "$ invested", "value": prettify(f"{avg_cost:.1f}")},
            {
                "label": "$ Last",
                "value": prettify(f"{last_value:.1f}"),
                "delta": prettify(f"{pnl:.1f}"),
            },
        ]
        for i, m in enumerate(l_metrics):
            cols[i % len(cols)].metric(**m)

    with tab_trades:
        st.write(df_buys)
        st.write(df_sells)
    with tab_divs:
        st.write(df_divs)


def closed_trade_pnl(symbol: str, df_activities: pd.DataFrame) -> dict:
    """Summarize realized PnL for one closed symbol from its activities alone.

    Mirrors the closed-position branch of :func:`show_activities`: proceeds from
    sells minus cost of buys plus dividends collected. ``sell`` quantities are
    stored negative by Questrade, so proceeds and the closed quantity are negated.

    Args:
        symbol: Ticker to summarize.
        df_activities: Activities frame with ``symbol``/``action``/``type``/
            ``price``/``quantity``/``netAmount``/``tradeDate`` columns.

    Returns:
        A dict with keys ``symbol``, ``realizedPnl``, ``total_return``, ``cost``,
        ``proceeds``, ``dividends``, ``buy_qty``, ``sell_qty``, ``is_complete``,
        ``last_date`` and ``days``. ``is_complete`` is True only when buy and sell
        quantities reconcile (a fully-closed round trip).

    Example:
        >>> df = pd.DataFrame(
        ...     [
        ...         {"symbol": "AAA", "action": "Buy", "type": "Trades",
        ...          "price": 10.0, "quantity": 100, "netAmount": -1000.0,
        ...          "tradeDate": "2026-01-01"},
        ...         {"symbol": "AAA", "action": "Sell", "type": "Trades",
        ...          "price": 12.0, "quantity": -100, "netAmount": 1200.0,
        ...          "tradeDate": "2026-02-01"},
        ...     ]
        ... )
        >>> r = closed_trade_pnl("AAA", df)
        >>> float(r["realizedPnl"]), r["is_complete"]
        (200.0, True)
    """
    _dfa = df_activities[df_activities["symbol"] == symbol]
    df_buys = _dfa[_dfa["action"] == "Buy"]
    df_sells = _dfa[_dfa["action"] == "Sell"]
    df_divs = _dfa[_dfa["type"] == "Dividends"]

    cost = (df_buys["price"] * df_buys["quantity"]).sum()
    proceeds = (df_sells["price"] * df_sells["quantity"]).sum() * -1
    dividends = df_divs["netAmount"].sum()
    realized_pnl = proceeds - cost + dividends

    buy_qty = df_buys["quantity"].sum()
    sell_qty = -df_sells["quantity"].sum()

    last_date = (
        pd.to_datetime(df_sells["tradeDate"].max()).date() if len(df_sells) else None
    )
    days = (
        (
            pd.to_datetime(df_sells["tradeDate"].max())
            - pd.to_datetime(df_buys["tradeDate"].min())
        ).days
        if len(df_buys) and len(df_sells)
        else 0
    )

    return {
        "symbol": symbol,
        "realizedPnl": realized_pnl,
        "total_return": realized_pnl / cost if cost else float("nan"),
        "cost": cost,
        "proceeds": proceeds,
        "dividends": dividends,
        "buy_qty": buy_qty,
        "sell_qty": sell_qty,
        "is_complete": bool(buy_qty > 0 and buy_qty == sell_qty),
        "last_date": last_date,
        "days": days,
    }


def summarize_closed_trades(
    closed_syms: list[str], df_activities: pd.DataFrame
) -> pd.DataFrame:
    """Build a one-row-per-symbol PnL summary for ``closed_syms``.

    Args:
        closed_syms: Symbols that are no longer held but appear in activities.
        df_activities: Activities frame (see :func:`closed_trade_pnl`).

    Returns:
        A DataFrame of :func:`closed_trade_pnl` rows. Empty (with the expected
        columns) when ``closed_syms`` is empty.
    """
    rows = [closed_trade_pnl(s, df_activities) for s in closed_syms]
    columns = [
        "symbol",
        "realizedPnl",
        "total_return",
        "cost",
        "proceeds",
        "dividends",
        "buy_qty",
        "sell_qty",
        "is_complete",
        "last_date",
        "days",
    ]
    return pd.DataFrame(rows, columns=columns)
