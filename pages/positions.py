"""Dashboard page: Positions / Orders / Activities / Balance tabs."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from questlit.ui.controls import account_dates_sidebar
from questlit.ui.data import (
    load_activities,
    load_orders,
    load_positions,
)
from questlit.ui.formatting import currency_column_config, position_df_styler
from questlit.ui.trades import show_activities


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
        # print(f"{sym}: {len(_dfo)} orders, stoplimit {sell_q} shares at {sell_p}")

        df_pos.at[i, "stopQuantity"] = sell_q
        df_pos.at[i, "stopPrice"] = sell_p

    for c in ["stopQuantity", "stopPrice"]:
        df_pos[c] = df_pos[c].astype(float)
    df_pos["stopQuantity"] = df_pos["stopQuantity"].astype("Int64")
    # print(df_pos["openQuantity"].dtype)
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


def main() -> None:
    target_acc, start_ts, end_ts = account_dates_sidebar()

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
