"""Shared dataframe-formatting helpers for Streamlit pages."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def currency_column_config(
    df: pd.DataFrame,
    exclude_cols: list = ["symbolId", "openQuantity", "closedQuantity"],
    format_exp: str = "%,.2f",
) -> dict:
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
    print(num_cols)
    dt_cols = df.select_dtypes(include=["datetime"]).columns.tolist()
    return {
        col: st.column_config.NumberColumn(format=format_exp)
        for col in num_cols
        if col not in exclude_cols
    } | {col: st.column_config.DateColumn(format="YYYY-MM-DD") for col in dt_cols}


def position_df_styler(df: pd.DataFrame):
    pnl_col = [
        c
        for c in df.columns
        if c.endswith(("Pnl", "_yield", "_return")) or c in ["stopProfitPct"]
    ]
    warn_col = [c for c in df.columns if c in ["uncoveredQuantity"]]

    def _color_pnl(val):
        color = "green" if val > 0 else "red" if val < 0 else "black"
        return f"color: {color};"  # background-color: {"lightgreen" if val > 0 else "lightcoral"};'

    def _warn_col(val, threshold: float = 0):
        return f"background-color: {'LightSalmon' if val > threshold else 'HoneyDew'}"

    styler = df.style.applymap(_color_pnl, subset=pnl_col)
    if warn_col:
        styler = styler.applymap(_warn_col, subset=warn_col)
    return styler
