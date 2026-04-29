"""Streamlit auth gate for the Questrade refresh-token seed flow."""

from __future__ import annotations

import requests
import streamlit as st

from questlit.questrade import QuestradeAuthError
from questlit.ui.data import load_accounts

PORTAL_URL = "https://apphub.questrade.com/UI/UserApps.aspx"


def _render_seed_form(error: str | None = None) -> None:
    if error:
        st.error(error)
    st.info(
        f"Generate a personal-app refresh token at "
        f"[My Apps → Personal Apps]({PORTAL_URL}) and paste it below."
    )
    with st.form("questrade_seed"):
        seed = st.text_input("Refresh token", type="password")
        submitted = st.form_submit_button("Connect")
    if submitted:
        if not seed:
            st.error("Please paste a refresh token before connecting.")
            return
        st.session_state["pending_seed"] = seed
        load_accounts.clear()
        st.rerun()


def ensure_authenticated() -> list[dict]:
    """Return the Questrade accounts list, or render the seed form and stop.

    On success, the accounts list is also stashed in
    ``st.session_state["accounts"]`` so downstream pages can read it without
    refetching.
    """
    pending = st.session_state.pop("pending_seed", None)
    try:
        accounts = load_accounts(pending)
    except QuestradeAuthError:
        _render_seed_form()
        st.stop()
    except requests.HTTPError as exc:
        if getattr(exc.response, "status_code", None) == 400:
            _render_seed_form(
                "Refresh token rejected by Questrade. "
                "Generate a fresh one and try again."
            )
            st.stop()
        st.error(f"Failed to load accounts: {exc}")
        st.stop()
    except Exception as exc:
        st.error(f"Failed to load accounts: {exc}")
        st.stop()

    st.session_state["accounts"] = accounts
    return accounts
