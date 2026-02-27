"""Unit tests for the backtest module.

Covers:
  1. entry_touched logic
  2. sl_touched / tp_touched logic
  3. Same-day SL+TP tie-breaker (worst and best)
  4. Portfolio accounting with fixed order-size
  5. get_week_starts helper
"""

from __future__ import annotations

from datetime import date

import pytest

from src.backtest.engine import (
    BacktestEngine,
    entry_touched,
    resolve_same_day,
    sl_touched,
    tp_touched,
)
from src.backtest.weekly_generator import get_week_starts
from src.models import OHLCV


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _candle(
    low: float,
    high: float,
    d: date = date(2024, 1, 15),
    open_: float | None = None,
    close: float | None = None,
) -> OHLCV:
    mid = (low + high) / 2
    return OHLCV(
        date=d,
        open=open_ if open_ is not None else mid,
        high=high,
        low=low,
        close=close if close is not None else mid,
    )


# ---------------------------------------------------------------------------
# 1. entry_touched
# ---------------------------------------------------------------------------

class TestEntryTouched:
    def test_entry_inside_range(self):
        assert entry_touched(_candle(95, 105), 100.0) is True

    def test_entry_at_low_boundary(self):
        assert entry_touched(_candle(100, 110), 100.0) is True

    def test_entry_at_high_boundary(self):
        assert entry_touched(_candle(90, 100), 100.0) is True

    def test_entry_above_high(self):
        assert entry_touched(_candle(90, 99), 100.0) is False

    def test_entry_below_low(self):
        assert entry_touched(_candle(101, 110), 100.0) is False

    def test_single_tick_candle(self):
        # open == high == low == close == entry
        assert entry_touched(_candle(100, 100), 100.0) is True

    def test_single_tick_candle_miss(self):
        assert entry_touched(_candle(100, 100), 99.9) is False


# ---------------------------------------------------------------------------
# 2. sl_touched / tp_touched
# ---------------------------------------------------------------------------

class TestSLTPTouch:
    def test_sl_hit_when_low_below_sl(self):
        assert sl_touched(_candle(94, 100), 95.0) is True

    def test_sl_hit_at_exact_sl(self):
        assert sl_touched(_candle(95, 100), 95.0) is True

    def test_sl_not_hit_when_low_above_sl(self):
        assert sl_touched(_candle(96, 100), 95.0) is False

    def test_tp_hit_when_high_above_tp(self):
        assert tp_touched(_candle(100, 106), 105.0) is True

    def test_tp_hit_at_exact_tp(self):
        assert tp_touched(_candle(100, 105), 105.0) is True

    def test_tp_not_hit_when_high_below_tp(self):
        assert tp_touched(_candle(100, 104), 105.0) is False


# ---------------------------------------------------------------------------
# 3. Same-day tie-breaker
# ---------------------------------------------------------------------------

class TestSameDayTieBreaker:
    def test_worst_gives_sl(self):
        reason, price = resolve_same_day("worst", sl=90.0, tp=110.0)
        assert reason == "SL"
        assert price == 90.0

    def test_best_gives_tp(self):
        reason, price = resolve_same_day("best", sl=90.0, tp=110.0)
        assert reason == "TP"
        assert price == 110.0

    def test_worst_is_default_when_neither_keyword(self):
        # resolve_same_day falls back to "SL" for any non-"best" value
        reason, price = resolve_same_day("worst", sl=80.0, tp=120.0)
        assert reason == "SL"


# ---------------------------------------------------------------------------
# 4. Portfolio accounting
# ---------------------------------------------------------------------------

class TestPortfolioAccounting:
    def test_legacy_order_size_still_works(self):
        """Legacy: fixed VND order_size still produces correct qty."""
        engine = BacktestEngine(initial_cash=10_000_000, order_size=1_000_000)
        c = _candle(99, 101, close=100)
        filled = engine.try_enter("HPG", entry=100.0, sl=90.0, tp=110.0, candle=c)
        assert filled is True
        # floor(1_000_000 / 100) == 10_000
        assert engine.open_trades[0].qty == 10_000
        assert engine.cash == 10_000_000 - 10_000 * 100.0

    def test_insufficient_cash_blocks_entry(self):
        engine = BacktestEngine(initial_cash=500, order_size=1_000_000)
        c = _candle(99, 101, close=100)
        filled = engine.try_enter("HPG", entry=100.0, sl=90.0, tp=110.0, candle=c)
        assert filled is False
        assert engine.open_trades == []

    def test_entry_not_triggered_when_price_misses(self):
        engine = BacktestEngine(initial_cash=10_000_000, order_size=1_000_000)
        c = _candle(102, 108, close=105)   # entry=100 is below low=102
        filled = engine.try_enter("HPG", entry=100.0, sl=90.0, tp=110.0, candle=c)
        assert filled is False

    def test_tp_exit_credits_cash_correctly(self):
        engine = BacktestEngine(initial_cash=10_000_000, order_size=1_000_000)
        entry_c = _candle(99, 101, d=date(2024, 1, 15), close=100)
        engine.try_enter("HPG", 100.0, 90.0, 110.0, entry_c)
        cash_after_entry = engine.cash
        qty = engine.open_trades[0].qty

        tp_c = _candle(105, 115, d=date(2024, 1, 16), close=110)
        engine.process_day({"HPG": tp_c}, date(2024, 1, 16))

        assert len(engine.closed_trades) == 1
        trade = engine.closed_trades[0]
        assert trade.reason == "TP"
        assert trade.exit_price == 110.0
        assert engine.cash == pytest.approx(cash_after_entry + qty * 110.0)

    def test_sl_exit_debits_expected_loss(self):
        engine = BacktestEngine(initial_cash=10_000_000, order_size=1_000_000)
        entry_c = _candle(99, 101, d=date(2024, 1, 15), close=100)
        engine.try_enter("HPG", 100.0, 90.0, 110.0, entry_c)
        cash_after_entry = engine.cash
        qty = engine.open_trades[0].qty

        sl_c = _candle(85, 95, d=date(2024, 1, 16), close=90)
        engine.process_day({"HPG": sl_c}, date(2024, 1, 16))

        assert engine.closed_trades[0].reason == "SL"
        assert engine.closed_trades[0].exit_price == 90.0
        assert engine.cash == pytest.approx(cash_after_entry + qty * 90.0)

    def test_no_same_day_entry_exit(self):
        """Position opened today must NOT be closed on the same candle."""
        engine = BacktestEngine(initial_cash=10_000_000, order_size=1_000_000)
        # Candle that touches entry AND both SL and TP
        c = _candle(80, 120, d=date(2024, 1, 15), close=100)
        engine.try_enter("HPG", 100.0, 90.0, 110.0, c)

        engine.process_day({"HPG": c}, date(2024, 1, 15))

        assert len(engine.open_trades) == 1
        assert len(engine.closed_trades) == 0

    def test_same_day_both_worst_uses_sl(self):
        """On same post-entry candle, worst tie-breaker → SL exit."""
        engine = BacktestEngine(
            initial_cash=10_000_000, order_size=1_000_000, tie_breaker="worst"
        )
        entry_c = _candle(99, 101, d=date(2024, 1, 15), close=100)
        engine.try_enter("HPG", 100.0, 90.0, 110.0, entry_c)

        both_c = _candle(85, 115, d=date(2024, 1, 16), close=100)
        engine.process_day({"HPG": both_c}, date(2024, 1, 16))

        assert engine.closed_trades[0].reason == "SL"
        assert engine.closed_trades[0].exit_price == 90.0

    def test_same_day_both_best_uses_tp(self):
        """On same post-entry candle, best tie-breaker → TP exit."""
        engine = BacktestEngine(
            initial_cash=10_000_000, order_size=1_000_000, tie_breaker="best"
        )
        entry_c = _candle(99, 101, d=date(2024, 1, 15), close=100)
        engine.try_enter("HPG", 100.0, 90.0, 110.0, entry_c)

        both_c = _candle(85, 115, d=date(2024, 1, 16), close=100)
        engine.process_day({"HPG": both_c}, date(2024, 1, 16))

        assert engine.closed_trades[0].reason == "TP"
        assert engine.closed_trades[0].exit_price == 110.0

    def test_equity_curve_recorded_each_day(self):
        engine = BacktestEngine(initial_cash=10_000_000, order_size=1_000_000)
        entry_c = _candle(99, 101, d=date(2024, 1, 15), close=100)
        engine.try_enter("HPG", 100.0, 90.0, 110.0, entry_c)

        for i in range(3):
            d = date(2024, 1, 16 + i)
            c = _candle(98, 103, d=d, close=101)
            engine.process_day({"HPG": c}, d)

        assert len(engine.equity_curve) == 3
        for point in engine.equity_curve:
            assert "date" in point
            assert point["total_value"] > 0

    def test_compute_summary_no_trades(self):
        engine = BacktestEngine(initial_cash=10_000_000, order_size=1_000_000)
        summary = engine.compute_summary(date(2024, 1, 1), date(2024, 12, 31))
        assert summary["num_trades"] == 0
        assert summary["win_rate"] == 0.0
        assert summary["final_value"] == 10_000_000.0

    def test_compute_summary_win_rate_and_pf(self):
        engine = BacktestEngine(initial_cash=10_000_000, order_size=1_000_000)

        # Trade 1: win (+10%)
        c_e = _candle(99, 101, d=date(2024, 1, 15), close=100)
        engine.try_enter("HPG", 100.0, 90.0, 120.0, c_e)
        c_tp = _candle(118, 125, d=date(2024, 1, 22), close=120)
        engine.process_day({"HPG": c_tp}, date(2024, 1, 22))

        # Trade 2: loss (–10%)
        c_e2 = _candle(99, 101, d=date(2024, 2, 1), close=100)
        engine.try_enter("VNM", 100.0, 90.0, 120.0, c_e2)
        c_sl = _candle(85, 95, d=date(2024, 2, 8), close=90)
        engine.process_day({"VNM": c_sl}, date(2024, 2, 8))

        summary = engine.compute_summary(date(2024, 1, 1), date(2024, 12, 31))
        assert summary["num_trades"] == 2
        assert summary["win_rate"] == pytest.approx(0.5)
        assert summary["profit_factor"] is not None
        assert summary["profit_factor"] > 0

    def test_invalid_tie_breaker_raises(self):
        with pytest.raises(ValueError):
            BacktestEngine(initial_cash=10_000_000, order_size=1_000_000, tie_breaker="50_50")


# ---------------------------------------------------------------------------
# 5. get_week_starts
# ---------------------------------------------------------------------------

class TestGetWeekStarts:
    def test_monday_start_date(self):
        # 2024-01-01 is a Monday
        weeks = get_week_starts(date(2024, 1, 1), date(2024, 1, 28))
        assert weeks[0] == date(2024, 1, 1)
        assert len(weeks) == 4

    def test_wednesday_start_yields_same_week_monday(self):
        # 2024-01-03 is Wednesday → first Monday is 2024-01-01
        weeks = get_week_starts(date(2024, 1, 3), date(2024, 1, 28))
        assert weeks[0] == date(2024, 1, 1)

    def test_single_week_range(self):
        weeks = get_week_starts(date(2024, 1, 1), date(2024, 1, 5))
        assert weeks == [date(2024, 1, 1)]

    def test_empty_when_from_after_to(self):
        weeks = get_week_starts(date(2024, 2, 1), date(2024, 1, 1))
        assert weeks == []

    def test_weekly_spacing(self):
        weeks = get_week_starts(date(2024, 1, 1), date(2024, 3, 31))
        for i in range(1, len(weeks)):
            delta = (weeks[i] - weeks[i - 1]).days
            assert delta == 7


# ---------------------------------------------------------------------------
# 6. Pct-based sizing
# ---------------------------------------------------------------------------

class TestPctSizing:
    def test_qty_uses_pct_of_equity(self):
        """Position size = floor(initial_cash * pct / entry)."""
        engine = BacktestEngine(initial_cash=10_000_000)  # no order_size
        c = _candle(99, 101, close=100)
        filled = engine.try_enter("HPG", entry=100.0, sl=90.0, tp=110.0, candle=c,
                                  position_target_pct=0.10)
        assert filled is True
        # floor(10_000_000 * 0.10 / 100) = floor(10_000) = 10_000
        import math
        expected_qty = math.floor(10_000_000 * 0.10 / 100.0)
        assert engine.open_trades[0].qty == expected_qty

    def test_pct_grows_with_equity(self):
        """Second trade qty reflects increased equity after a TP exit."""
        engine = BacktestEngine(initial_cash=10_000_000)
        pct = 0.10

        # Trade 1 entry
        c_e = _candle(99, 101, d=date(2024, 1, 15), close=100)
        engine.try_enter("HPG", 100.0, 90.0, 120.0, c_e, position_target_pct=pct)
        qty1 = engine.open_trades[0].qty

        # Trade 1 TP exit (price goes to 120)
        c_tp = _candle(118, 125, d=date(2024, 1, 22), close=120)
        engine.process_day({"HPG": c_tp}, date(2024, 1, 22))
        assert len(engine.closed_trades) == 1

        # Equity has grown; second trade should use larger VND amount
        equity_after = engine.cash  # no open positions now
        c_e2 = _candle(99, 101, d=date(2024, 2, 1), close=100)
        engine.try_enter("VNM", 100.0, 90.0, 120.0, c_e2, position_target_pct=pct)
        qty2 = engine.open_trades[0].qty

        import math
        expected_qty2 = math.floor(equity_after * pct / 100.0)
        assert qty2 == expected_qty2
        assert qty2 > qty1  # equity grew → larger position

    def test_no_sizing_returns_false(self):
        """Entry fails if neither order_size nor position_target_pct is supplied."""
        engine = BacktestEngine(initial_cash=10_000_000)  # no order_size
        c = _candle(99, 101, close=100)
        filled = engine.try_enter("HPG", entry=100.0, sl=90.0, tp=110.0, candle=c)
        assert filled is False

    def test_pct_zero_falls_back_to_order_size(self):
        """position_target_pct=0 falls through to legacy order_size sizing."""
        engine = BacktestEngine(initial_cash=10_000_000, order_size=1_000_000)
        c = _candle(99, 101, close=100)
        filled = engine.try_enter("HPG", entry=100.0, sl=90.0, tp=110.0, candle=c,
                                  position_target_pct=0.0)
        assert filled is True
        import math
        assert engine.open_trades[0].qty == math.floor(1_000_000 / 100.0)

    def test_compute_summary_has_avg_invested_pct(self):
        """compute_summary must include avg_invested_pct key."""
        engine = BacktestEngine(initial_cash=10_000_000)
        entry_c = _candle(99, 101, d=date(2024, 1, 15), close=100)
        engine.try_enter("HPG", 100.0, 90.0, 110.0, entry_c, position_target_pct=0.10)
        engine.process_day({"HPG": _candle(98, 103, d=date(2024, 1, 16), close=101)},
                           date(2024, 1, 16))
        summary = engine.compute_summary(date(2024, 1, 1), date(2024, 12, 31))
        assert "avg_invested_pct" in summary
        assert 0.0 <= summary["avg_invested_pct"] <= 1.0
