"""Dashboard page: Positions / Orders / Activities / Balance tabs."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from questlit.ui.data import (
    load_activities,
    load_balances,
    load_orders,
    load_positions,
)
from questlit.ui.formatting import currency_column_config


def _show_balance() -> None:
    balance = load_balances()
    df = pd.DataFrame(balance)
    st.dataframe(
        df,
        hide_index=True,
        height="content",
        column_config=currency_column_config(df),
    )


def main() -> None:
    accounts = st.session_state["accounts"]
    acc_dict = {f"{a['number']} ({a['type']})": a["number"] for a in accounts}
    st.dataframe(pd.DataFrame(accounts), hide_index=True)

    tab_pos, tab_orders, tab_activities, tab_balance = st.tabs(
        ["Positions", "Orders", "Activities", "Balance"]
    )

    with tab_pos:
        positions = load_positions()
        if not positions:
            st.info("No open positions.")
        else:
            st.dataframe(
                pd.DataFrame(positions),
                width="content",
                hide_index=True,
                height="content",
            )

    with tab_orders:
        cols = st.columns(2)
        target_acc = cols[0].selectbox(
            "select account", options=[a["number"] for a in accounts]
        )
        start_date = (
            cols[1].datetime_input(
                "start date", value=pd.Timestamp.now().normalize()
            )
            if cols[1].toggle("use start date")
            else None
        )
        orders = load_orders(target_acc, start_time=start_date)
        st.dataframe(pd.DataFrame(orders), hide_index=True, height="content")

    with tab_activities:
        cols = st.columns(2)
        user_acc = cols[0].selectbox(
            "select account",
            options=acc_dict.keys(),
            key="acc_activities",
        )
        target_acc = acc_dict[user_acc]
        start_date = cols[1].datetime_input(
            "Activities start date",
            value=pd.Timestamp.now().normalize() - pd.Timedelta(days=30),
        )
        activities = load_activities(
            target_acc,
            start_time=start_date,
            end_time=pd.Timestamp.now().ceil("D"),
        )
        st.dataframe(pd.DataFrame(activities), hide_index=True, height="content")

    with tab_balance:
        _show_balance()


main()
