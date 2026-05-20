"""QuestLit Streamlit entrypoint: auth gate + multipage navigation."""

import streamlit as st

from questlit.ui.auth import ensure_authenticated


def main() -> None:
    st.set_page_config(page_title="QuestLit", layout="wide", page_icon="asset/logo.png")
    ensure_authenticated()

    st.navigation(
        [
            st.Page("pages/welcome.py", title="welcome"),
            st.Page(
                "pages/dashboard.py",
                title="Overview",
                icon=":material/dashboard:",
            ),
            st.Page(
                "pages/positions.py",
                title="positions",
                icon=":material/dashboard:",
            ),
            st.Page(
                "pages/candles.py",
                title="Candles",
                icon=":material/candlestick_chart:",
            ),
        ],
        position="top",
    ).run()


if __name__ == "__main__":
    main()
