from datetime import datetime

import pandas as pd
import requests
import streamlit as st

from questlit.questrade import QuestradeAuthError, QuestradeClient

PORTAL_URL = "https://apphub.questrade.com/UI/UserApps.aspx"


@st.cache_data(ttl="1d")
def load_accounts(_seed: str | None = None) -> list[dict]:
    return QuestradeClient(seed_refresh_token=_seed).get_accounts()


@st.cache_data(ttl=60)
def load_positions(_seed: str | None = None) -> list[dict]:
    return QuestradeClient(seed_refresh_token=_seed).get_all_positions()


@st.cache_data(ttl=60)
def load_balances() -> list[dict]:
    return QuestradeClient().get_all_balances()


@st.cache_data(ttl=60)
def load_orders(
    account_id: str | int, start_time: datetime | None = None
) -> list[dict]:
    return QuestradeClient().get_orders(
        account_id, start_time=start_time, state_filter="All"
    )


@st.cache_data(ttl=60)
def load_activities(
    account_id: str | int, start_time: datetime, end_time: datetime
) -> list[dict]:
    return QuestradeClient().get_activities(
        account_id, start_time=start_time, end_time=end_time
    )


def _render_seed_form(error: str | None = None) -> None:
    if error:
        st.error(error)
    st.info(
        f"Generate a personal-app refresh token at [My Apps → Personal Apps]({PORTAL_URL}) and paste it below."
    )
    with st.form("questrade_seed"):
        seed = st.text_input("Refresh token", type="password")
        submitted = st.form_submit_button("Connect")
    if submitted:
        if not seed:
            st.error("Please paste a refresh token before connecting.")
            return
        st.session_state["pending_seed"] = seed
        load_positions.clear()
        st.rerun()


def init_acc():
    pending = st.session_state.pop("pending_seed", None)
    try:
        # positions = load_positions(pending)
        # return positions
        accounts = load_accounts(pending)
        return accounts
    except QuestradeAuthError:
        _render_seed_form()
        st.stop()
    except requests.HTTPError as exc:
        if getattr(exc.response, "status_code", None) == 400:
            _render_seed_form(
                "Refresh token rejected by Questrade. Generate a fresh one and try again."
            )
            st.stop()
        st.error(f"Failed to load accounts: {exc}")
        st.stop()
    except Exception as exc:
        st.error(f"Failed to load accounts: {exc}")
        st.stop()
    return None


def show_balance():
    balance = load_balances()
    _df = pd.DataFrame(balance)

    # Get all numeric columns (or maybe just 'integer' or 'float')
    num_cols = _df.select_dtypes(include=["number"]).columns.tolist()

    # Create column config for all numeric columns
    column_config = {
        col: st.column_config.NumberColumn(format="$%.2f") for col in num_cols
    }

    st.dataframe(
        _df,
        hide_index=True,
        height="content",
        column_config=column_config,
        # column_config={
        #     "cash": st.column_config.NumberColumn(format="$%.2f"),
        #     "totalEquity": st.column_config.NumberColumn(format="$%.2f"),
        # },
    )


def main():
    st.set_page_config(page_title="QuestLit", layout="wide")
    # positions = init_pos()
    accounts = init_acc()
    acc_dict = {f"{a['number']} ({a['type']})": a["number"] for a in accounts}
    st.dataframe(pd.DataFrame(accounts), hide_index=True)

    tab_pos, tab_orders, tab_activities, tab_balance = st.tabs(
        ["Positions", "Orders", "Activities", "balance"]
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
            cols[1].datetime_input("start date", value=pd.Timestamp.now().normalize())
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
        show_balance()


if __name__ == "__main__":
    main()
