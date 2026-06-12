import streamlit as st
import yaml

from questlit.ui.controls import tv_url


@st.cache_data(ttl=60)
def load_shortlist(path: str = "asset/shortlist.yaml") -> list[str]:
    """Load the watchlist symbols from a shortlist YAML file.

    Args:
        path: Path to the shortlist file, relative to the app's working
            directory (the repo root, where ``streamlit run`` is launched).

    Returns:
        The list of symbols under the file's ``symbols:`` key (empty if absent).
    """
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("symbols", [])


def candle_url(symbol: str) -> str:
    """Build a link to the candles page deep-linked to ``symbol``.

    Mirrors the inline pattern in :mod:`questlit.ui.trades`: take the current
    page URL, set the ``symbol`` query param, then swap the page slug for
    ``candles`` so the link works from any page.
    """
    return f"{st.context.url}/candles?symbol={symbol}"


def main():
    st.title("Welcome")
    cols = st.columns(4)
    shortlist_container = cols[0].expander("shortlist", expanded=True)

    with shortlist_container:
        r_col, l_col = st.columns(2)
        for symbol in load_shortlist():
            r_col.page_link(
                candle_url(symbol),
                label=symbol.upper(),
                icon=":material/candlestick_chart:",
                help="view chart",
            )
            l_col.page_link(
                tv_url(symbol),
                label="overview",
                icon=":material/link:",
                help=f"view {symbol.upper()} on TradingView",
            )


main()
