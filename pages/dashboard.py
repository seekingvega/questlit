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
    # account selection
    accounts = st.session_state["accounts"]
    acc_dict = {f"{a['number']} ({a['type']})": a["number"] for a in accounts}
    with st.sidebar:
        select_acc = st.selectbox(
            "Account",
            help="select an account to view past trades for your Symbol",
            options=[""] + list(acc_dict.keys()),
            key="account",
            bind="query-params",
        )
        target_acc = acc_dict[select_acc] if select_acc else None
        info_container = st.expander("Accounts")
    info_container.dataframe(pd.DataFrame(accounts), hide_index=True)

    tab_pos, tab_orders, tab_activities, tab_balance = st.tabs(
        ["Positions", "Orders", "Activities", "Balance"]
    )

    with tab_pos:
        positions = load_positions(account_id=target_acc)
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
        if not target_acc:
            st.warning(f"please select account in sidebar :point_left:")
        else:
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
        if not target_acc:
            st.warning(f"please select account in sidebar :point_left:")
        else:
            cols = st.columns((2, 1, 2))
            start_dt = cols[0].datetime_input(
                "Activities Start date",
                value=pd.Timestamp.now().normalize() - pd.Timedelta(days=30),
            )
            end_dt = (
                cols[2].datetime_input(
                    "Activities End date",
                    min_value=start_dt + pd.Timedelta(days=1),
                    value=pd.Timestamp.now().normalize(),
                )
                if cols[1].toggle("provide end date")
                else pd.Timestamp.now().ceil("D")
            )
            slim_activities = cols[1].toggle(
                "clean activities view",
                value=True,
                help="remove some columns from view",
            )
            activities = load_activities(
                target_acc,
                start_time=start_dt,
                end_time=end_dt,
            )
            df_activities = pd.DataFrame(activities)

            # activity filters
            cols = st.columns(4)
            target_sym = cols[0].selectbox(
                "Symbols Filter",
                options=[""] + df_activities["symbol"].unique().tolist(),
            )
            target_type = cols[1].multiselect(
                "activitiy type Filter",
                options=df_activities["type"].unique(),
                default=df_activities["type"].unique(),
            )
            df_activities = (
                df_activities[df_activities["symbol"] == target_sym]
                if target_sym
                else df_activities
            )
            df_activities = (
                df_activities[df_activities["type"].isin(target_type)]
                if target_type
                else df_activities
            )
            slim_activities_cols = [
                c
                for c in df_activities.columns
                if c
                not in [
                    "transactionDate",
                    "settlementDate",
                    "symbolId",
                    "grossAmount",
                    "commission",
                ]
            ]
            df_activities = (
                df_activities[slim_activities_cols]
                if slim_activities
                else df_activities
            )
            st.dataframe(
                df_activities.sort_values(by=["tradeDate"], ascending=False),
                hide_index=True,
                height="content",
            )

    with tab_balance:
        _show_balance()


main()
