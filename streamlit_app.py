import pandas as pd
import requests
import streamlit as st

from questlit.questrade import QuestradeAuthError, QuestradeClient

PORTAL_URL = "https://apphub.questrade.com/UI/UserApps.aspx"


@st.cache_data(ttl=60)
def load_positions(_seed: str | None = None) -> list[dict]:
    return QuestradeClient(seed_refresh_token=_seed).get_all_positions()


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


def init_pos():
    pending = st.session_state.pop("pending_seed", None)
    try:
        positions = load_positions(pending)
        return positions
    except QuestradeAuthError:
        _render_seed_form()
        st.stop()
    except requests.HTTPError as exc:
        if getattr(exc.response, "status_code", None) == 400:
            _render_seed_form(
                "Refresh token rejected by Questrade. Generate a fresh one and try again."
            )
            st.stop()
        st.error(f"Failed to load positions: {exc}")
        st.stop()
    except Exception as exc:
        st.error(f"Failed to load positions: {exc}")
        st.stop()
    return None


def main():
    st.set_page_config(page_title="QuestLit", layout="wide")
    positions = init_pos()

    st.title("Current Positions")
    if not positions:
        st.info("No open positions.")
    else:
        st.dataframe(pd.DataFrame(positions), width="content")


if __name__ == "__main__":
    main()
