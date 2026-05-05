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

    The profile rides on a dedicated overlay x-axis (``xaxis3``) anchored to
    row 1's price y-axis, so it does not collide with the volume row's
    ``xaxis2`` reserved by ``make_subplots(rows=2)``.
    """
    my_volume_profile = get_volume_profile(data=df, do_round=False)

    fig.add_trace(
        go.Bar(
            x=my_volume_profile.values,
            y=my_volume_profile.index,
            orientation="h",
            name="Volume Profile",
            xaxis="x3",
            yaxis="y",
            marker_color="Gold",  # "rgba(100, 150, 250, 0.3)",
            opacity=0.3,
            hoverinfo="x+y",
        )
    )
    # Render the volume-profile bars behind the candles and gridlines.
    fig.data = (fig.data[-1],) + fig.data[:-1]

    fig.update_layout(
        xaxis3=dict(
            overlaying="x",
            side="top",
            showticklabels=False,
            showgrid=False,
            # Stretch range so bars hug the left ~25% of the candle area.
            range=[0, my_volume_profile.max() * 4],
        ),
        # Re-assert grid on the candle subplot's primary axes — Plotly's
        # overlay-axis rendering otherwise drops them on the underlying axes.
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True),
    )

    return fig
