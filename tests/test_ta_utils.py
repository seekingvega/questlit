"""Tests for questlit.ui.ta_utils.

Only ``add_moving_average`` is exercised — it's the sole symbol from this
module that the rest of the project actually imports.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from questlit.ui.ta_utils import add_moving_average


def _ohlc_df(closes, volumes=None):
    n = len(closes)
    return pd.DataFrame(
        {
            "Close": closes,
            "Volume": volumes if volumes is not None else [100] * n,
        }
    )


def test_add_moving_average_ema_adds_named_column():
    df = _ohlc_df([10, 11, 12, 13, 14])
    out = add_moving_average(df, period=3, type="ema")
    assert out is df
    assert "ema_3" in out.columns
    assert pd.isna(out["ema_3"].iloc[0])
    assert out["ema_3"].iloc[1:].notna().all()


def test_add_moving_average_sma_matches_pandas_rolling_mean():
    df = _ohlc_df([1.0, 2.0, 3.0, 4.0, 5.0])
    add_moving_average(df, period=3, type="sma")
    expected = df["Close"].rolling(3).mean().shift()
    pd.testing.assert_series_equal(df["sma_3"], expected, check_names=False)


def test_add_moving_average_vwap_uses_volume_weighted_formula():
    df = _ohlc_df([10.0, 20.0, 30.0], volumes=[1.0, 1.0, 1.0])
    add_moving_average(df, period=2, type="vwap")
    expected = pd.Series([np.nan, np.nan, 15.0], name="vwap_2")
    pd.testing.assert_series_equal(
        df["vwap_2"].reset_index(drop=True),
        expected,
        check_names=False,
    )


def test_add_moving_average_custom_price_col():
    df = pd.DataFrame({"close": [1, 2, 3, 4], "Volume": [1, 1, 1, 1]})
    add_moving_average(df, period=2, type="sma", price_col="close")
    assert "sma_2" in df.columns
    assert df["sma_2"].iloc[2:].notna().all()


def test_add_moving_average_missing_price_col_raises():
    df = pd.DataFrame({"NotClose": [1, 2, 3]})
    with pytest.raises(AssertionError, match="Close"):
        add_moving_average(df, period=2)


def test_add_moving_average_unknown_type_raises():
    df = _ohlc_df([1, 2, 3])
    with pytest.raises(AssertionError, match="bogus"):
        add_moving_average(df, period=2, type="bogus")
