"""Tests for closed-trade PnL classification in ``questlit.ui.trades``.

Pure-pandas: no Streamlit runtime is exercised. Activities mirror the Questrade
shape that ``show_activities`` reads — ``Sell`` quantities are stored negative.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from questlit.ui.trades import closed_trade_pnl, summarize_closed_trades


def _act(symbol, action, type_, price, quantity, net_amount, trade_date):
    return {
        "symbol": symbol,
        "action": action,
        "type": type_,
        "price": price,
        "quantity": quantity,
        "netAmount": net_amount,
        "tradeDate": trade_date,
    }


@pytest.fixture
def df_activities() -> pd.DataFrame:
    """A winner, a loser (with a dividend), and an incomplete (half-sold) trade."""
    return pd.DataFrame(
        [
            # WIN: buy 100 @ 10, sell 100 @ 12 -> +200
            _act("WIN", "Buy", "Trades", 10.0, 100, -1000.0, "2026-01-01"),
            _act("WIN", "Sell", "Trades", 12.0, -100, 1200.0, "2026-03-01"),
            # LOSE: buy 50 @ 20, sell 50 @ 18, +10 dividend -> -90
            _act("LOSE", "Buy", "Trades", 20.0, 50, -1000.0, "2026-01-15"),
            _act("LOSE", "Sell", "Trades", 18.0, -50, 900.0, "2026-02-15"),
            _act("LOSE", "", "Dividends", 0.0, 0, 10.0, "2026-02-01"),
            # PARTIAL: bought 100, only sold 40 within the window
            _act("PARTIAL", "Buy", "Trades", 5.0, 100, -500.0, "2026-01-10"),
            _act("PARTIAL", "Sell", "Trades", 6.0, -40, 240.0, "2026-02-10"),
        ]
    )


def test_winning_trade(df_activities):
    r = closed_trade_pnl("WIN", df_activities)
    assert r["realizedPnl"] == pytest.approx(200.0)
    assert r["is_complete"] is True
    assert r["total_return"] == pytest.approx(0.2)
    assert r["days"] == 59


def test_losing_trade_includes_dividends(df_activities):
    r = closed_trade_pnl("LOSE", df_activities)
    # proceeds 900 - cost 1000 + div 10 = -90
    assert r["realizedPnl"] == pytest.approx(-90.0)
    assert r["dividends"] == pytest.approx(10.0)
    assert r["is_complete"] is True


def test_incomplete_trade_flagged(df_activities):
    r = closed_trade_pnl("PARTIAL", df_activities)
    assert r["buy_qty"] == 100
    assert r["sell_qty"] == 40
    assert r["is_complete"] is False


def test_summarize_classifies_all(df_activities):
    summary = summarize_closed_trades(["WIN", "LOSE", "PARTIAL"], df_activities)
    assert list(summary["symbol"]) == ["WIN", "LOSE", "PARTIAL"]

    complete = summary[summary["is_complete"]]
    winners = complete[complete["realizedPnl"] > 0]
    losers = complete[complete["realizedPnl"] <= 0]
    incomplete = summary[~summary["is_complete"]]

    assert list(winners["symbol"]) == ["WIN"]
    assert list(losers["symbol"]) == ["LOSE"]
    assert list(incomplete["symbol"]) == ["PARTIAL"]


def test_summarize_empty_has_columns():
    summary = summarize_closed_trades([], pd.DataFrame())
    assert summary.empty
    assert "realizedPnl" in summary.columns and "is_complete" in summary.columns


def test_total_return_nan_when_no_cost():
    df = pd.DataFrame(
        [_act("DIVONLY", "", "Dividends", 0.0, 0, 5.0, "2026-01-01")]
    )
    r = closed_trade_pnl("DIVONLY", df)
    assert math.isnan(r["total_return"])
    assert r["is_complete"] is False
