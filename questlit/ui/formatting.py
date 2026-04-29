"""Shared dataframe-formatting helpers for Streamlit pages."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def currency_column_config(df: pd.DataFrame) -> dict:
    """Return a column-config mapping that formats every numeric column as USD.

    Args:
        df: DataFrame whose numeric columns should render as currency.

    Returns:
        A dict suitable for ``st.dataframe(column_config=...)``.

    Example:
        >>> import pandas as pd
        >>> df = pd.DataFrame({"name": ["a"], "cash": [1.5], "qty": [2]})
        >>> cfg = currency_column_config(df)
        >>> sorted(cfg.keys())
        ['cash', 'qty']
    """
    num_cols = df.select_dtypes(include=["number"]).columns.tolist()
    return {col: st.column_config.NumberColumn(format="$%.2f") for col in num_cols}
