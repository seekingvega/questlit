"""Dashboard page: Positions / Orders / Activities / Balance tabs."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import streamlit as st
from millify import millify, prettify

from pages.candles import _parse_range, get_st_app_url
from questlit.ui.data import (
    load_activities,
    load_balances,
    load_orders,
    load_positions,
)
from questlit.ui.formatting import currency_column_config, position_df_styler


def add_stop_orders(df_pos, df_orders):
    df_pos = df_pos.set_index("symbolId")
    df_pos["stopQuantity"] = 0
    df_pos["stopPrice"] = None
    for i, sym in zip(df_pos.index.tolist(), df_pos["symbol"].tolist()):
        _dfo = df_orders[
            (df_orders["symbol"] == sym)
            & (df_orders["side"] == "Sell")
            & (df_orders["orderType"] == "StopLimit")
        ]
        # print(_dfo)
        sell_q = _dfo["openQuantity"].sum()
        sell_p = (_dfo["openQuantity"] * _dfo["stopPrice"]).sum() / sell_q
        print(f"{sym}: {len(_dfo)} orders, stoplimit {sell_q} shares at {sell_p}")

        df_pos.at[i, "stopQuantity"] = sell_q
        df_pos.at[i, "stopPrice"] = sell_p

    for c in ["stopQuantity", "stopPrice"]:
        df_pos[c] = df_pos[c].astype(float)
    df_pos["stopQuantity"] = df_pos["stopQuantity"].astype("Int64")
    print(df_pos["openQuantity"].dtype)
    df_pos["uncoveredQuantity"] = df_pos["openQuantity"] - df_pos["stopQuantity"]
    df_pos["stopProfitPct"] = df_pos["stopPrice"] / df_pos["averageEntryPrice"] - 1
    return df_pos


def add_activities(df_pos, df_activities, end_ts):
    df_pos["buy_order_count"] = 0
    df_pos["dividends_collected"] = 0.0
    df_pos["days_invested"] = 0
    end_naive = (
        pd.Timestamp(end_ts).tz_localize(None)
        if pd.Timestamp(end_ts).tzinfo
        else pd.Timestamp(end_ts)
    )
    for i, sym in zip(df_pos.index.tolist(), df_pos["symbol"].tolist()):
        _dfa = df_activities[df_activities["symbol"] == sym]
        _buys = _dfa[_dfa["action"] == "Buy"]
        df_pos.at[i, "buy_order_count"] = len(_buys)
        df_pos.at[i, "dividends_collected"] = _dfa.loc[
            _dfa["type"] == "Dividends", "netAmount"
        ].sum()
        if len(_buys):
            first_buy = (
                pd.to_datetime(_buys["tradeDate"], utc=True).dt.tz_localize(None).min()
            )
            df_pos.at[i, "days_invested"] = (end_naive - first_buy).days

    # computing Dividend Yield
    principal = df_pos["openQuantity"] * df_pos["averageEntryPrice"]
    t_years = df_pos["days_invested"] / 365.0
    valid = (t_years > 0) & (principal > 0)
    yld = pd.Series(np.nan, index=df_pos.index)
    yld[valid] = (
        np.log1p(df_pos.loc[valid, "dividends_collected"] / principal[valid])
        / t_years[valid]
    )
    df_pos["dividend_yield"] = yld

    # compute Captial Gain
    ratio = df_pos["currentPrice"] / df_pos["averageEntryPrice"]
    cg = pd.Series(np.nan, index=df_pos.index)
    cg_valid = valid & (ratio > 0)
    cg[cg_valid] = np.log(ratio[cg_valid]) / t_years[cg_valid]
    # df_pos["capital_gain"] = cg
    df_pos["capital_return"] = ratio - 1
    return df_pos


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

    # getting candle url
    candle_qp = st.query_params.to_dict() | {"symbol": symbol}
    if last_date:
        candle_qp["end"] = last_date + timedelta(days=1)
    else:
        candle_qp.pop("end", None)
    candle_url = get_st_app_url(qp=candle_qp).replace("positions", "candles")

    tab_dash, tab_trades, tab_divs = st_container.tabs(
        ["Overview", "Trades", "Dividends"]
    )

    with tab_dash:
        # st.write(candle_url)

        cols = st.columns(4)
        # display_dict = {
        #     "symbol": f"[{symbol}]({candle_url})",
        #     "days invested": days,
        #     "status": ":green[open]" if is_open else f":gray[closed]",
        #     "$ invested": prettify(f"{avg_cost:.1f}"),
        #     "$ Last": prettify(f"{last_value:.1f}"),
        #     "$ Dividend Paid": prettify(f"{div_paid:.1f}"),
        #     "PnL": prettify(f"{pnl:.1f}"),
        #     "Div Yield": f"{div_paid/avg_cost:.1%}",
        #     "Total Return": f"{pnl/avg_cost:.1%}",
        # }
        # for i, (k, v) in enumerate(display_dict.items()):
        #     cols[i % len(cols)].metric(k, v)
        #     # if k:
        #     #     cols[i % len(cols)].metric(k, v)
        #     # else:
        #     #     cols[i % len(cols)].write("nothing")

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
            # {
            #     "label": "status",
            #     "value": ":green[open]" if is_open else f":gray[closed]",
            # },
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


def main() -> None:
    # account selection
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
        st.warning(f"please select an account to continue :point_left:")
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

    positions = load_positions(account_id=target_acc)
    orders = load_orders(
        target_acc, start_time=start_ts, end_time=end_ts, state_filter="Open"
    )
    orders = [
        o
        for o in orders
        if o["state"] in ["Accepted", "ContingentOrder"]
        and o["side"] == "Sell"
        and o["orderType"] == "StopLimit"
    ]
    activities = load_activities(
        target_acc,
        start_time=start_ts,
        end_time=end_ts,
    )
    activities = [a for a in activities if a["type"] in ["Dividends", "Trades"]]

    tab_pos, tab_orders, tab_activities = st.tabs(
        [
            f"{len(positions)} Positions",
            f"{len(orders)} orders found",
            f"{len(activities)} activities found",
        ]
    )
    with tab_pos:
        if not positions:
            st.info("No open positions.")
        else:
            hidden_col = ["dayPnl", "totalCost", "isUnderReorg"]
            df_pos = add_stop_orders(pd.DataFrame(positions), pd.DataFrame(orders))
            df_pos = add_activities(df_pos, pd.DataFrame(activities), end_ts)
            df_pos = df_pos.drop(columns=hidden_col).sort_values(
                by=["currentMarketValue"]
            )
            st.dataframe(
                position_df_styler(df_pos),
                width="content",
                hide_index=True,
                height="content",
                column_config=currency_column_config(df_pos)
                | {
                    "stopProfitPct": st.column_config.NumberColumn(format="percent"),
                    "dividend_yield": st.column_config.NumberColumn(
                        format="percent",
                        help=(
                            "Continuously-compounded yield: ln(1 + divs/principal) / t. "
                            "t bounded by sidebar Range — older positions undercounted."
                        ),
                    ),
                    "capital_return": st.column_config.NumberColumn(
                        format="percent",
                        help="simple return (i.e. NOT annualized)",
                        # help=(
                        #     "Annualized continuously-compounded price return: "
                        #     "ln(currentPrice/averageEntryPrice) / t. "
                        #     "t bounded by sidebar Range — older positions overstated."
                        # ),
                    ),
                },
            )
    df_orders = pd.DataFrame(orders)
    df_activities = pd.DataFrame(activities)
    with tab_orders:
        st.dataframe(df_orders)
    with tab_activities:
        st.dataframe(df_activities)

    closed_sym = [
        s
        for s in df_activities["symbol"].unique()
        if s not in df_pos["symbol"].unique()
    ]
    # select_closed_sym = st.sidebar.selectbox("Closed Symbols", options=closed_sym)
    select_pos_sym = st.sidebar.selectbox(
        "Select Position to View :point_right:",
        options=df_pos["symbol"].unique().tolist(),
    )
    show_activities(
        select_pos_sym,
        df_pos=df_pos,
        df_activities=pd.DataFrame(activities),
        st_container=st.expander(f"Position View for {select_pos_sym}", expanded=True),
    )


main()
