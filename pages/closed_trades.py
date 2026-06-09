"""Closed Trades page: split closed round-trips into winners / losers, drill in.

Reuses the shared sidebar (`account_dates_sidebar`), the closed-trade PnL helpers
(`summarize_closed_trades`) and the per-symbol deep-dive (`show_activities`) so the
only page-specific logic is the winner/loser/incomplete grouping and layout.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from questlit.ui.controls import account_dates_sidebar
from questlit.ui.data import load_activities, load_positions
from questlit.ui.formatting import currency_column_config, position_df_styler
from questlit.ui.trades import show_activities, summarize_closed_trades


def _table_config(df: pd.DataFrame) -> dict:
    """Currency formatting for dollar columns, percent for ``total_return``."""
    cfg = currency_column_config(
        df, exclude_cols=["total_return", "buy_qty", "sell_qty", "days"]
    )
    cfg["total_return"] = st.column_config.NumberColumn(format="percent")
    return cfg


def _show_table(df: pd.DataFrame, caption: str | None = None) -> None:
    if caption:
        st.caption(caption)
    if df.empty:
        st.info("Nothing here for the selected account and date range.")
        return
    st.dataframe(
        position_df_styler(df),
        hide_index=True,
        column_config=_table_config(df),
    )


def main() -> None:
    target_acc, start_ts, end_ts = account_dates_sidebar()

    positions = load_positions(account_id=target_acc)
    df_pos = pd.DataFrame(positions)
    if "symbol" not in df_pos.columns:  # no open positions -> show_activities needs it
        df_pos["symbol"] = pd.Series(dtype="object")

    activities = [
        a
        for a in load_activities(target_acc, start_time=start_ts, end_time=end_ts)
        if a["type"] in ("Dividends", "Trades")
    ]
    df_act = pd.DataFrame(activities)
    if df_act.empty:
        st.info("No trade activities found for the selected account and date range.")
        st.stop()

    open_syms = set(df_pos["symbol"])
    closed_sym = [s for s in df_act["symbol"].unique() if s not in open_syms]
    if not closed_sym:
        st.info("No closed trades in this window — every traded symbol is still held.")
        st.stop()

    summary = summarize_closed_trades(closed_sym, df_act)
    complete = summary[summary["is_complete"]]
    winners = complete[complete["realizedPnl"] > 0].sort_values(
        "realizedPnl", ascending=False
    )
    losers = complete[complete["realizedPnl"] <= 0].sort_values("realizedPnl")
    incomplete = summary[~summary["is_complete"]]

    tab_w, tab_l, tab_i = st.tabs(
        [
            f"{len(winners)} Winners",
            f"{len(losers)} Losers",
            f"{len(incomplete)} Incomplete",
        ]
    )
    with tab_w:
        _show_table(winners)
    with tab_l:
        _show_table(losers)
    with tab_i:
        _show_table(
            incomplete,
            caption=(
                "Buy/sell quantities don't reconcile in this window — widen the "
                "sidebar Range to capture the missing trades."
            ),
        )

    # Sidebar selectbox over all closed symbols, annotated with realized PnL.
    pnl_by_sym = summary.set_index("symbol")["realizedPnl"]
    ordered = (
        winners["symbol"].tolist()
        + losers["symbol"].tolist()
        + incomplete["symbol"].tolist()
    )
    sel = st.sidebar.selectbox(
        "Select Closed Trade :point_right:",
        options=ordered,
        format_func=lambda s: f"{s} ({pnl_by_sym[s]:+,.0f})",
    )
    show_activities(
        sel,
        df_pos=df_pos,
        df_activities=df_act,
        st_container=st.expander(f"Trade View for {sel}", expanded=True),
    )


main()
