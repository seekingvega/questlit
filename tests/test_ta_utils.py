"""Tests for questlit.ui.ta_utils.

Exercises the helpers the rest of the project imports: ``add_moving_average``,
``add_MACD``, and ``add_RSI``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from questlit.ui.ta_utils import add_MACD, add_RSI, add_moving_average


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


def test_add_MACD_adds_three_columns():
    df = _ohlc_df(list(range(1, 41)))
    out = add_MACD(df, fast=12, slow=26, signal=9)
    assert out is df
    for col in ("MACD", "MACD_signal", "MACD_histogram"):
        assert col in out.columns
    # signal needs `slow + signal - 1` warm-up rows before it's defined
    assert out["MACD_signal"].iloc[-1] == pytest.approx(out["MACD_signal"].iloc[-1])
    assert pd.notna(out["MACD_signal"].iloc[-1])


def test_add_MACD_histogram_equals_macd_minus_signal():
    df = _ohlc_df([10.0 + i * 0.5 for i in range(50)])
    add_MACD(df, fast=12, slow=26, signal=9)
    expected = df["MACD"] - df["MACD_signal"]
    pd.testing.assert_series_equal(
        df["MACD_histogram"], expected, check_names=False
    )


def test_add_MACD_custom_price_col():
    df = pd.DataFrame({"close": [10.0 + i * 0.3 for i in range(50)]})
    add_MACD(df, fast=12, slow=26, signal=9, price_col="close")
    assert "MACD" in df.columns
    assert pd.notna(df["MACD"].iloc[-1])


def test_add_RSI_adds_rsi_column():
    df = _ohlc_df([10.0 + (i % 5) * 0.5 for i in range(40)])
    out = add_RSI(df, n=14)
    assert out is df
    assert "RSI" in out.columns
    rsi_valid = out["RSI"].dropna()
    assert (rsi_valid.between(0, 100)).all()


def test_add_RSI_custom_price_col():
    df = pd.DataFrame({"close": [10.0 + (i % 7) * 0.4 for i in range(40)]})
    add_RSI(df, n=14, price_col="close")
    assert "RSI" in df.columns
    assert pd.notna(df["RSI"].iloc[-1])
    assert 0 <= df["RSI"].iloc[-1] <= 100
