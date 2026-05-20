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
from questlit.ui.formatting import currency_column_config, position_df_styler


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
            df_pos = pd.DataFrame(positions)
            st.dataframe(
                position_df_styler(df_pos),
                width="content",
                hide_index=True,
                height="content",
                column_config=currency_column_config(df_pos),
            )

    with tab_orders:
        cols = st.columns((2, 2, 1, 2))
        if not target_acc:
            st.warning(f"please select account in sidebar :point_left:")
        else:
            order_type = cols[0].selectbox("order type", ["Open", "All", "Closed"])
            start_date = (
                cols[3].datetime_input(
                    "start date",
                    value=pd.Timestamp.now().normalize() - pd.Timedelta(days=30),
                )
                if cols[2].toggle("use start date", value=True)
                else None
            )
            orders = load_orders(
                target_acc, start_time=start_date, state_filter=order_type
            )
            order_cols = [
                "symbol",
                "totalQuantity",
                "openQuantity",
                "filledQuantity",
                "canceledQuantity",
                "side",
                "orderType",
                "limitPrice",
                "stopPrice",
                "avgExecPrice",
                "timeInForce",
                "state",
                "rejectionReason",
                "updateTime",
                "creationTime",
            ]
            df_orders = pd.DataFrame(orders)[order_cols].sort_values(
                ["updateTime", "creationTime"], ascending=False
            )
            state_filter = cols[1].multiselect(
                "Order State",
                options=df_orders["state"].unique(),
                default=(
                    [
                        s
                        for s in df_orders["state"].unique()
                        if s in ["Accepted", "ContingentOrder"]
                    ]
                    if order_type == "Open"
                    else df_orders["state"].unique()
                ),
            )
            symbol_filter = cols[0].selectbox(
                "symbol filter", options=[""] + df_orders["symbol"].unique().tolist()
            )
            orders_filter = df_orders["state"].isin(state_filter)
            orders_filter &= (
                (df_orders["symbol"] == symbol_filter) if symbol_filter else True
            )
            st.dataframe(
                df_orders[orders_filter],
                hide_index=True,
                height="content",
                column_config=currency_column_config(df_orders),
            )

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
