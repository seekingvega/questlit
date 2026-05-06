import pandas as pd
import plotly.graph_objects as go


# compute volume profile
def get_volume_profile(
    data: pd.DataFrame, base: int = 2, num_bins: int = 20, do_round: bool = False
):
    if do_round:
        df = data[["close", "volume"]].copy()
        # Round to nearest X
        df["Last"] = df["close"].apply(lambda x: round(x, base))
        # Remove the date index
        df = df.set_index("Last")[["volume"]]
        df = df.groupby(["Last"], observed=True).sum()
    else:
        # We bin the prices and sum the volume for each bin
        price_buckets = pd.cut(data["close"], bins=num_bins)
        volume_profile = data.groupby(price_buckets, observed=True)["volume"].sum()
        # Get the midpoint of each price bin for the Y-axis coordinates
        volume_profile.index = [interval.mid for interval in volume_profile.index]
        df = volume_profile
    return df


def add_volume_profile(fig, df: pd.DataFrame):
    """Overlay a horizontal volume-by-price profile on the candle subplot.

    The profile rides on a dedicated overlay x-axis anchored to row 1's price
    y-axis. The overlay axis index is picked dynamically as the first free
    ``xaxisN`` slot above those reserved by ``make_subplots`` so it doesn't
    clobber an existing subplot row's x-axis (e.g. ``xaxis3`` is row 3 when
    the figure has 3 rows).
    """
    my_volume_profile = get_volume_profile(data=df, do_round=False)

    # Find the next free xaxisN slot (xaxis, xaxis2, ... are reserved by make_subplots).
    idx = 2
    while f"xaxis{idx}" in fig.layout:
        idx += 1
    axis_layout_key = f"xaxis{idx}"
    axis_ref = f"x{idx}"

    fig.add_trace(
        go.Bar(
            x=my_volume_profile.values,
            y=my_volume_profile.index,
            orientation="h",
            name="Volume Profile",
            xaxis=axis_ref,
            yaxis="y",
            marker_color="Gold",  # "rgba(100, 150, 250, 0.3)",
            opacity=0.3,
            hoverinfo="x+y",
        )
    )
    # Render the volume-profile bars behind the candles and gridlines.
    fig.data = (fig.data[-1],) + fig.data[:-1]

    fig.update_layout(
        **{
            axis_layout_key: dict(
                overlaying="x",
                side="top",
                showticklabels=False,
                showgrid=False,
                # Stretch range so bars hug the left ~25% of the candle area.
                range=[0, my_volume_profile.max() * 4],
            )
        },
        # Re-assert grid on the candle subplot's primary axes — Plotly's
        # overlay-axis rendering otherwise drops them on the underlying axes.
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True),
    )

    return fig


def get_moving_average_col(df_columns):
    return [
        c for c in df_columns if "_" in c and c.split("_")[0] in ["ema", "sma", "vwap"]
    ]


_EMA_COLORS = ["Violet", "YellowGreen", "Teal", "HotPink", "LimeGreen"]


def plot_moving_averages(fig, df):
    """Overlay pre-computed EMA lines on the candle subplot, one trace per period.

    Pure plotting helper: expects each ``ema_{period}`` column to already
    exist on ``df`` (use ``add_moving_average`` from
    ``questlit.ui.ta_utils``). This decoupling lets callers compute EMAs on
    a wider warm-up window and then slice ``df`` down to the visible range
    before plotting, which keeps early EMA values stable.

    Args:
        fig: A ``plotly.graph_objects.Figure`` whose row=1 is the candlestick.
        df: Candles dataframe with a ``start`` timestamp column and an
            ``ema_{period}`` column for each requested period.
        periods: Iterable of positive int EMA periods to plot. Colors cycle
            through ``_EMA_COLORS`` in order.

    Returns:
        The figure, mutated in place and returned for chaining.
    """
    target_cols = get_moving_average_col(df.columns)
    for i, col in enumerate(target_cols):
        fig.add_trace(
            go.Scatter(
                x=df["start"],
                y=df[col],
                mode="lines",
                name=col,
                line=dict(color=_EMA_COLORS[i % len(_EMA_COLORS)], width=1),
                opacity=0.8,
            ),
            row=1,
            col=1,
        )
    return fig


def add_impulse_trace(
    fig,
    df,
    date_col=None,
    ohlc_col_map={"o": "Open", "h": "High", "l": "Low", "c": "Close"},
    l_rgb_css_color_name=["red", "green", "DodgerBlue"],
):
    """add candlestick trace on top to show impulse system
    ref: https://stackoverflow.com/a/66998861/14285096
    """
    df_green = df[df["impulse"] == 1]
    df_red = df[df["impulse"] == -1]
    df_blue = df[df["impulse"] == 0]

    l_trace_def = [
        {"name": "long or short", "df": df_blue, "color": l_rgb_css_color_name[2]},
        {"name": "long only", "df": df_green, "color": l_rgb_css_color_name[1]},
        {"name": "short only", "df": df_red, "color": l_rgb_css_color_name[0]},
    ]
    for trace in l_trace_def:
        df = trace["df"]
        fig.add_trace(
            go.Candlestick(
                x=df[date_col] if date_col else df.index,
                open=df[ohlc_col_map["o"]],
                high=df[ohlc_col_map["h"]],
                low=df[ohlc_col_map["l"]],
                close=df[ohlc_col_map["c"]],
                name=trace["name"],
                increasing_line_color=trace["color"],
                decreasing_line_color=trace["color"],
            ),
            row=1,
            col=1,
        )
    return fig


def add_ADX_trace(
    fig,
    df,
    ref_row,
    ref_col=1,
    date_col=None,
    line_color_map={"ADX": "Yellow", "+DMI": "DarkOliveGreen", "-DMI": "DarkRed"},
):
    date_serie = df[date_col] if date_col else df.index
    for k, v in line_color_map.items():
        fig.append_trace(
            go.Scatter(x=date_serie, y=df[k], name=k, line={"color": v}),
            row=ref_row,
            col=ref_col,
        )
    return fig


def add_MACD_trace(fig, df, ref_row, ref_col=1, date_col=None, draw_signal_line=True):
    """Plot MACD histogram (always) and MACD/signal lines (optional) on one subplot row.

    Histogram bars are colored green when ``MACD_histogram >= 0`` and red when
    negative — the standard MACD convention. When ``draw_signal_line`` is True,
    the MACD line (Gold), signal line (DarkGrey) and a dashed zero reference
    line (Grey) are overlaid on the same row.

    Args:
        fig: A ``plotly.graph_objects.Figure`` built via ``make_subplots``.
        df: DataFrame with ``MACD``, ``MACD_signal``, ``MACD_histogram`` columns
            (use ``add_MACD`` from ``questlit.ui.ta_utils``).
        ref_row: 1-indexed subplot row to draw on.
        ref_col: 1-indexed subplot column.
        date_col: Column name to use for the x-axis. Defaults to ``df.index``.
        draw_signal_line: If True, overlay the MACD line, signal line and zero
            reference line on top of the histogram.

    Returns:
        The figure, mutated in place and returned for chaining.
    """
    for c in ["MACD", "MACD_histogram", "MACD_signal"]:
        assert c in df.columns, f"required column {c} is missing from input df"

    date_serie = df[date_col] if date_col else df.index
    bar_colors = [
        "MediumSeaGreen" if v >= 0 else "Crimson" for v in df["MACD_histogram"]
    ]

    fig.add_trace(
        go.Bar(
            x=date_serie,
            y=df["MACD_histogram"],
            name="MACD_histogram",
            marker_color=bar_colors,
            opacity=0.6,
        ),
        row=ref_row,
        col=ref_col,
    )

    if draw_signal_line:
        fig.add_trace(
            go.Scatter(
                x=date_serie,
                y=df["MACD"],
                name="MACD",
                line={"color": "Gold", "width": 1.5},
            ),
            row=ref_row,
            col=ref_col,
        )
        fig.add_trace(
            go.Scatter(
                x=date_serie,
                y=df["MACD_signal"],
                name="MACD_signal",
                line={"color": "DarkGrey", "width": 1.5},
            ),
            row=ref_row,
            col=ref_col,
        )
        fig.add_trace(
            go.Scatter(
                x=date_serie,
                y=[0] * len(date_serie),
                name="MACD_0",
                line={"color": "Grey", "width": 1, "dash": "dash"},
                showlegend=False,
                hoverinfo="skip",
            ),
            row=ref_row,
            col=ref_col,
        )
    return fig


def add_RSI_trace(fig, df, ref_row, ref_col=1, date_col=None, hi=70, lo=30):
    """Plot RSI as a line on one subplot row with dotted hi/lo reference lines.

    Args:
        fig: A ``plotly.graph_objects.Figure`` built via ``make_subplots``.
        df: DataFrame with an ``RSI`` column (use ``add_RSI`` from
            ``questlit.ui.ta_utils``).
        ref_row: 1-indexed subplot row to draw on.
        ref_col: 1-indexed subplot column.
        date_col: Column name to use for the x-axis. Defaults to ``df.index``.
        hi: Upper threshold (overbought reference line). Defaults to 70.
        lo: Lower threshold (oversold reference line). Defaults to 30.

    Returns:
        The figure, mutated in place and returned for chaining.
    """
    assert "RSI" in df.columns, "required column RSI is missing from input df"

    date_serie = df[date_col] if date_col else df.index

    fig.add_trace(
        go.Scatter(
            x=date_serie,
            y=df["RSI"],
            mode="lines",
            name="RSI",
            line={"color": "MediumPurple", "width": 1.5},
        ),
        row=ref_row,
        col=ref_col,
    )
    for level, color in ((hi, "Crimson"), (lo, "MediumSeaGreen")):
        fig.add_trace(
            go.Scatter(
                x=date_serie,
                y=[level] * len(date_serie),
                name=f"RSI {level}",
                line={"color": color, "width": 1, "dash": "dot"},
                showlegend=False,
                hoverinfo="skip",
            ),
            row=ref_row,
            col=ref_col,
        )
    return fig


def add_Scatter(fig, df, target_col, date_col=None, line_color=None):
    date_serie = df[date_col] if date_col else df.index
    fig.append_trace(
        go.Scatter(
            x=date_serie,
            y=df[target_col],
            name=target_col,
            line={"color": line_color} if line_color else None,
        ),
        row=1,
        col=1,
    )
    return fig


def add_Scatter_Event(
    fig,
    df,
    target_col,
    anchor_col,
    textposition="top center",
    fontsize=None,
    marker_symbol=None,
    event_label=None,
    date_col=None,
):
    """add non-zero points in target_col as events to the main chart"""
    df_ = df[df[target_col] != 0].copy()
    date_serie = df_[date_col] if date_col else df_.index

    if event_label:  # ensure it is the right size
        event_label = (
            event_label
            if type(event_label) == list
            else [event_label for i in range(len(date_serie))]
        )

    # for marker styling see: https://plotly.com/python/marker-style/

    fig.append_trace(
        go.Scatter(
            x=date_serie,
            y=df_[anchor_col],
            mode="markers+text",
            name=target_col,
            marker_symbol=marker_symbol,
            textposition=textposition,
            textfont_size=fontsize,
            text=event_label if event_label else df_[target_col],
        ),
        row=1,
        col=1,
    )
    return fig
