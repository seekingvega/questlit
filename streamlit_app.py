import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from questlit.questrade import QuestradeClient

load_dotenv()

st.set_page_config(page_title="QuestLit", layout="wide")
st.title("Current Positions")


@st.cache_data(ttl=60)
def load_positions() -> list[dict]:
    return QuestradeClient().get_all_positions()


try:
    positions = load_positions()
except Exception as exc:
    st.error(f"Failed to load positions: {exc}")
    st.stop()

if not positions:
    st.info("No open positions.")
else:
    st.dataframe(pd.DataFrame(positions), use_container_width=True)
