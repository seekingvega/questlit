###############################################################################
# Inspiration from quantmod (https://github.com/jackluo/py-quantmod)
# & this kaggle notebook (https://www.kaggle.com/mtszkw/technical-indicators-for-trading-stocks)
#
# all functions accept input df from yfinance with columns:
#  ['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']
###############################################################################
import os
import sys

import numpy as np
import pandas as pd


def add_moving_average(
    df, period: int, type: str = "ema", price_col="Close", vol_col="Volume"
):
    """
    add a new column with moving average
    args:
        period: number of bars (row) in the df
        type: ema, sma, vwap
        price_col: name of the column to apply the calculation on
    """
    assert (
        price_col in df.columns
    ), f"add_moving_average: {price_col} not found in df provided."
    ma_dict = {
        "ema": df[price_col].ewm(period).mean().shift(),
        "sma": df[price_col].rolling(period).mean().shift(),
        "vwap": (df[price_col] * df[vol_col]).rolling(period).sum().shift()
        / df[vol_col].rolling(period).sum().shift(),
    }
    assert (
        type in ma_dict.keys()
    ), f"add_moving_average: type {type} is not one of {ma_dict.keys()}"

    new_col_name = f"{type}_{period}"
    df[new_col_name] = ma_dict[type]
    return df


def add_MACD(df, fast: int = 12, slow: int = 26, signal: int = 9, price_col="Close"):
    ema_fast = df[price_col].ewm(span=fast, min_periods=fast).mean()
    ema_slow = df[price_col].ewm(span=slow, min_periods=slow).mean()
    MACD = ema_fast - ema_slow
    MACD_signal = MACD.ewm(span=signal, min_periods=signal).mean()
    df["MACD_histogram"] = MACD - MACD_signal
    df["MACD"] = MACD
    df["MACD_signal"] = MACD_signal
    return df


def add_ATR(
    df,
    period: int = 13,
    use_ema: bool = False,
    channel_dict: dict | None = None,
    col_name: str | None = None,
    return_TR: bool = True,
    normalize: bool = False,
    high_col: str = "High",
    low_col: str = "Low",
    close_col: str = "Close",
):
    """Average True Range (ATR), a volatility indicator.

    Computes True Range row-wise as
    ``max(high - low, |high - prev_close|, |low - prev_close|)`` then
    averages it over ``period`` bars (simple by default; EMA if
    ``use_ema=True``). Mutates ``df`` in place by adding ``ATR`` (or
    ``col_name`` if provided), and ``TR`` when ``return_TR=True``.

    Args:
        df: DataFrame with high/low/close columns.
        period: Lookback window for the moving average. Defaults to 13.
        use_ema: If True, use an exponential MA on True Range instead of
            a simple rolling mean.
        channel_dict: Optional ``{ma_col: [multiples]}`` mapping. For each
            entry, adds ``ch:{ma_col}+{m}atr`` / ``ch:{ma_col}-{m}atr``
            channels around an existing MA column. Skipped when ``None``.
        col_name: Output column name for ATR. Defaults to ``"ATR"``.
        return_TR: If True, also write the per-bar True Range as ``TR``.
        normalize: If True, divide ATR/TR by ``close_col`` (% of price).
        high_col: Name of the high column (defaults to ``"High"``).
        low_col: Name of the low column (defaults to ``"Low"``).
        close_col: Name of the close column (defaults to ``"Close"``).

    Returns:
        The mutated ``df`` for chaining.

    Examples:
        >>> import pandas as pd
        >>> df = pd.DataFrame({
        ...     "High":  [11.0, 12.0, 13.0, 14.0],
        ...     "Low":   [10.0, 11.0, 12.0, 13.0],
        ...     "Close": [10.5, 11.5, 12.5, 13.5],
        ... })
        >>> _ = add_ATR(df, period=2, return_TR=True)
        >>> sorted(set(df.columns) - {"High", "Low", "Close"})
        ['ATR', 'TR']

    ref: https://www.learnpythonwithrune.org/calculate-the-average-true-range-atr-easy-with-pandas-dataframes/
    ref: https://stackoverflow.com/questions/40256338/calculating-average-true-range-atr-on-ohlc-data-with-python
    """
    assert not (
        all([channel_dict, col_name])
    ), "channels can only be added on top of the base ATR (not when col_name is provided)"
    assert col_name not in df.columns, f"{col_name} already exists in input dataframe"

    high_low = df[high_col] - df[low_col]
    high_close = np.abs(df[high_col] - df[close_col].shift())
    low_close = np.abs(df[low_col] - df[close_col].shift())

    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)

    if return_TR:
        df["TR"] = true_range
        df["TR"] /= df[close_col] if normalize else 1
    col_name = col_name if col_name else "ATR"
    df[col_name] = (
        true_range.ewm(span=period).mean()
        if use_ema
        else true_range.rolling(period).mean()
    )
    df[col_name] /= df[close_col] if normalize else 1

    if channel_dict:
        for k, l_channels in channel_dict.items():
            assert k in df.columns, f"add_ATR: {k} is not found in input df."
            for c in l_channels:
                df[f"ch:{k}+{c}atr"] = df[k] + df["ATR"] * c
                df[f"ch:{k}-{c}atr"] = df[k] - df["ATR"] * c

    return df


def add_AD(df):
    """Accumulation/ Distribution"""
    df["A/D"] = (
        (df["Volume"] * (df["Close"] - df["Open"]) / (df["High"] - df["Low"]))
        .fillna(0)
        .cumsum()
    )
    return df


def add_OBV(df):
    """On Balance Volume
    ref: https://stackoverflow.com/a/66827219/14285096
    """
    obv = (np.sign(df["Close"].diff()) * df["Volume"]).fillna(0).cumsum()
    df["OBV"] = obv
    return df


def add_RSI(df, n: int = 14, price_col="Close"):
    """RSI
    ref: https://stackoverflow.com/a/57037866/14285096
    """

    def rma(x, n, y0):  # Running Moving Average
        a = (n - 1) / n
        ak = a ** np.arange(len(x) - 1, -1, -1)
        return np.r_[
            np.full(n, np.nan),
            y0,
            np.cumsum(ak * x) / ak / n + y0 * a ** np.arange(1, len(x) + 1),
        ]

    delta = df[price_col].diff()
    gains = delta.mask(delta < 0, 0.0)
    losses = -delta.mask(delta > 0, -0.0)
    avg_gain = rma(
        gains[n + 1 :].to_numpy(), n, np.nansum(gains.to_numpy()[: n + 1]) / n
    )
    avg_loss = rma(
        losses[n + 1 :].to_numpy(), n, np.nansum(losses.to_numpy()[: n + 1]) / n
    )
    df["RS"] = avg_gain / avg_loss
    df[f"RSI"] = 100 - (100 / (1 + df["RS"]))
    return df


def add_ADX(df, period: int):
    """Computes the ADX indicator.
    source: https://stackoverflow.com/a/64946213/14285096
    """
    alpha = 1 / period
    assert "ATR" in df.columns, f"ATR must be computed before computing ADX"
    # +-DX
    df["H-pH"] = df["High"] - df["High"].shift(1)
    df["pL-L"] = df["Low"].shift(1) - df["Low"]
    df["+DX"] = np.where((df["H-pH"] > df["pL-L"]) & (df["H-pH"] > 0), df["H-pH"], 0.0)
    df["-DX"] = np.where((df["H-pH"] < df["pL-L"]) & (df["pL-L"] > 0), df["pL-L"], 0.0)
    del df["H-pH"], df["pL-L"]

    # +- DMI
    df["S+DM"] = df["+DX"].ewm(alpha=alpha, adjust=False).mean()
    df["S-DM"] = df["-DX"].ewm(alpha=alpha, adjust=False).mean()
    df["+DMI"] = (df["S+DM"] / df["ATR"]) * 100
    df["-DMI"] = (df["S-DM"] / df["ATR"]) * 100
    del df["S+DM"], df["S-DM"]

    # ADX
    df["DX"] = (np.abs(df["+DMI"] - df["-DMI"]) / (df["+DMI"] + df["-DMI"])) * 100
    df["ADX"] = df["DX"].ewm(alpha=alpha, adjust=False).mean()
    del df["DX"], df["-DX"], df["+DX"]  # , df['+DMI'], df['-DMI']

    return df


def add_Impulse(df, ema_name, MACD_Hist_name="MACD_histogram"):
    """Elder's Impluse system
    positive sloping ema and positive sloping MACD Hist are green (1)
    negative sloping ema and negative sloping MACD Hist are red (-1)
    all other bars are blue (0)
    """
    assert ema_name in df.columns, f"{ema_name} not found in input df"
    assert MACD_Hist_name in df.columns, f"{MACD_Hist_name} missing in df"

    ema_diff = df[ema_name] - df[ema_name].shift()
    macd_hist_diff = df[MACD_Hist_name] - df[MACD_Hist_name].shift()
    df["impulse"] = np.array(
        [
            1 if d_ema > 0 and d_macdh > 0 else -1 if d_ema < 0 and d_macdh < 0 else 0
            for d_ema, d_macdh in zip(ema_diff, macd_hist_diff)
        ]
    )
    return df


def add_avg_penetration(
    df,
    hilo_col_names=("High", "Low"),
    fair_col="ema_11",
    num_of_bars: int = 30,
    use_ema=False,
    ignore_zero=True,
    coef=1,
    get_df=True,
    debug=False,
):
    """Calculate the average pentration below & above the fair and
        return buy and sell SafeZones
    Args:
        use_ema: use exponential moving average to compute average penetration
        ignore_zero: ignore days without penetration
        coef: applied to average penetration to create SafeZones
    """
    hi, lo = hilo_col_names
    assert hi in df.columns, f"{hi} not found in input df"
    assert lo in df.columns, f"{hi} not found in input df"
    assert fair_col in df.columns, f"{fair_col} not found in input df"
    assert len(df) >= num_of_bars, f"df only has {len(df)} bars"

    df_ = df.copy()
    df_["up"] = (df_[hi] - df_[fair_col]).clip(lower=0)  # upper penetration
    df_["lp"] = (df_[fair_col] - df_[lo]).clip(lower=0)  # lower penetration

    for pen in ["up", "lp"]:
        if use_ema:
            # ref: https://stackoverflow.com/a/64969439/14285096
            df_[f"avg_{pen}"] = (
                df_[pen]
                .replace(0, np.nan)
                .ewm(num_of_bars, ignore_na=True)
                .mean()
                .shift()
                if ignore_zero
                else df_[pen].ewm(num_of_bars, ignore_na=True).mean().shift()
            )
            df_[f"std_{pen}"] = (
                df_[pen].ewm(num_of_bars, ignore_na=True).std().shift()
                if ignore_zero
                else df_[pen].ewm(num_of_bars, ignore_na=True).std().shift()
            )
        else:  # simple average
            df_[f"avg_{pen}"] = (
                df_[pen].rolling(num_of_bars).apply(lambda x: x[x > 0].mean()).shift()
                if ignore_zero
                else df_[pen].rolling(num_of_bars).mean().shift()
            )
            df_[f"std_{pen}"] = (
                df_[pen].rolling(num_of_bars).apply(lambda x: x[x > 0].std()).shift()
                if ignore_zero
                else df_[pen].rolling(num_of_bars).std().shift()
            )
        df_[f"count_{pen}"] = (
            df_[pen].rolling(num_of_bars).apply(lambda x: x[x > 0].count()).shift()
        )

    df_["buy_safezone"] = df_[fair_col] - (df_["avg_lp"] * coef)
    df_["sell_safezone"] = df_[fair_col] + (df_["avg_up"] * coef)

    # expected_fair = df_[fair_col][-1] + (df_[fair_col][-1] - df_[fair_col][-2])
    if not debug and get_df:
        del df_["up"], df_["lp"]
        for p in ["up", "lp"]:
            del df_[f"avg_{p}"], df_[f"std_{p}"], df_[f"count_{p}"]

    return (
        df_
        if get_df
        else {
            "avg_upper_penetration": df_["avg_up"][-1],
            "stdv_upper_penetration": df_["std_up"][-1],
            "count_upper_penetration": df_["count_up"][-1],
            "avg_lower_penetration": df_["avg_lp"][-1],
            "stdv_lower_penetration": df_["std_lp"][-1],
            "count_lower_penetration": df_["count_lp"][-1],
            # 'expected_fair': expected_fair,
            # 'buy_target_t+1': expected_fair - df_['avg_lp'][-1]
        }
    )


def market_classification(
    df,
    period: int,
    debug=False,
    class_names_map={0: "rangebound", 1: "trending-up", -1: "trending-down"},
):
    """detect trending-up, trending-down, or rangebound"""

    # Calculates period highs and lows —
    # computes the rolling maximum and minimum over the given `period` window (shifted back by one bar)
    df["period_high"] = df["high"].rolling(period).max().shift()
    df["period_low"] = df["low"].rolling(period).min().shift()

    # Extracts unique values —
    # gets the unique period highs and lows from the last `period` bars and rounds them to 2 decimals
    highs = [round(p, 2) for p in df["period_high"][-period:].unique().tolist()]
    if debug:
        print(f"{period} bars highs: {highs}")
    hh = (
        sorted(highs) == highs
    )  #  checks if highs are in ascending order (**higher highs**)
    lh = (
        sorted(highs, reverse=True) == highs
    )  # checks if highs are in descending order (**lower highs**)

    lows = [round(p, 2) for p in df["period_low"][-period:].unique().tolist()]
    if debug:
        print(f"{period} bars lows: {lows}")
    ll = sorted(lows, reverse=True) == lows
    hl = sorted(lows) == lows

    mkt_cls = -1 if ll and lh else 0
    mkt_cls = 1 if hh and hl else mkt_cls
    return class_names_map[mkt_cls] if class_names_map else mkt_cls


def add_market_classification(
    df,
    period: int,
    col_name="market_classification",
    class_map={0: "rangebound", 1: "trending-up", -1: "trending-down"},
    debug_mode=False,
):
    """detect trending (up: higher highs + higher lows, down: lower highs + lower lows)
    or rangebound markets
    Args:
        period: number of bars to lookback (sliding window) for highs and lows
    """
    # def internal util functions
    round_list = lambda ll: [round(i, 2) for i in ll]
    is_ascending = lambda ll: sorted(ll) == ll
    is_descending = lambda ll: sorted(ll, reverse=True) == ll

    period_high = df["High"].rolling(period).max().shift()
    period_low = df["Low"].rolling(period).min().shift()

    is_pH = df["High"] == period_high
    is_pL = df["Low"] == period_low
    is_hh = (
        period_high.rolling(period)
        .apply(lambda ll: is_ascending(round_list(ll)))
        .fillna(0)
        .astype(bool)
    )
    is_hl = (
        period_low.rolling(period)
        .apply(lambda ll: is_ascending(round_list(ll)))
        .fillna(0)
        .astype(bool)
    )
    is_lh = (
        period_high.rolling(period)
        .apply(lambda ll: is_descending(round_list(ll)))
        .fillna(0)
        .astype(bool)
    )
    is_ll = (
        period_low.rolling(period)
        .apply(lambda ll: is_descending(round_list(ll)))
        .fillna(0)
        .astype(bool)
    )

    trend_up = is_hh & is_hl
    trend_down = is_lh & is_ll
    df[col_name] = [
        1 if up else -1 if down else 0
        for up, down in zip(trend_up.tolist(), trend_down.tolist())
    ]
    if class_map:
        df[col_name] = df[col_name].apply(lambda x: class_map[x])
    if debug_mode:
        df["period_high"] = period_high
        df["period_low"] = period_low
        df["higher_highs"] = is_hh
        df["higher_lows"] = is_hl
        df["lower_highs"] = is_lh
        df["lower_lows"] = is_ll

        # useful for Darvas Box?
        df["is_period_high"] = is_pH
        df["is_period_low"] = is_pL
    return df


def efficiency_ratio(df, period: int):
    """efficiency is defined as (close_t - close_0)/ sum(daily_hilo)"""
    diff = abs(df["Close"][-1] - df["Close"][-period])
    hilo = df["High"] - df["Low"]
    return diff / hilo[-period:].sum()


def add_KER(df, period: int, col_name="KER"):
    """add Kaufman's efficiency ratio to df"""
    hilo = df["High"] - df["Low"]
    hilo_sum = hilo.rolling(period).sum()
    diff = df["Close"].rolling(period).apply(lambda x: abs(x[-1] - x[0]))
    df["KER"] = diff / hilo_sum
    return df


def add_peaks(df, date_col=None, order=3):
    """local minima & maxima detection
    Args:
        order: how many points on each side to use for the comparison
    ref: https://eddwardo.github.io/posts/finding-local-extreams-in-pandas-time-series/
    """
    pass
