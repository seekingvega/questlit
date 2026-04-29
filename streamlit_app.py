"""QuestLit Streamlit entrypoint: auth gate + multipage navigation."""

import streamlit as st

from questlit.ui.auth import ensure_authenticated


def main() -> None:
    st.set_page_config(page_title="QuestLit", layout="wide")
    ensure_authenticated()

    st.navigation(
        [
            st.Page(
                "pages/dashboard.py",
                title="Dashboard",
                icon=":material/dashboard:",
            ),
            st.Page("pages/welcome.py", title="welcome"),
        ],
        position="top",
    ).run()


if __name__ == "__main__":
    main()
