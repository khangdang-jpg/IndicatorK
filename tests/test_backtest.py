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
from src.backtest.cli import _buy_priority_key, _parse_signal_days
from src.backtest.weekly_generator import get_signal_dates, get_week_starts
from src.models import OHLCV, Recommendation, WeeklyPlan
from src.utils.config import load_watchlist


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
        assert "sharpe_ratio" in summary
        assert "calmar_ratio" in summary
        assert "total_fees_paid" in summary

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

    def test_breakout_gap_up_fills_at_open_not_trigger(self):
        engine = BacktestEngine(initial_cash=10_000_000)
        c = _candle(101, 110, d=date(2024, 1, 15), open_=105, close=108)
        filled = engine.try_enter(
            "HPG", entry=100.0, sl=90.0, tp=120.0, candle=c,
            position_target_pct=0.10, entry_type="breakout"
        )
        assert filled is True
        assert engine.open_trades[0].entry_price == 105.0

    def test_stop_gap_down_exits_at_open_not_stop(self):
        engine = BacktestEngine(initial_cash=10_000_000, order_size=1_000_000)
        entry_c = _candle(99, 101, d=date(2024, 1, 15), open_=100, close=100)
        engine.try_enter("HPG", 100.0, 90.0, 110.0, entry_c)

        gap_down = _candle(80, 95, d=date(2024, 1, 16), open_=85, close=88)
        engine.process_day({"HPG": gap_down}, date(2024, 1, 16))

        assert engine.closed_trades[0].reason == "SL"
        assert engine.closed_trades[0].exit_price == 85.0

    def test_transaction_fees_reduce_cash_and_are_reported(self):
        engine = BacktestEngine(
            initial_cash=10_000_000,
            order_size=1_000_000,
            buy_fee_pct=0.001,
            sell_fee_pct=0.001,
            sell_tax_pct=0.001,
        )
        entry_c = _candle(99, 101, d=date(2024, 1, 15), open_=100, close=100)
        engine.try_enter("HPG", 100.0, 90.0, 110.0, entry_c)

        qty = engine.open_trades[0].qty
        expected_entry_fee = qty * 100.0 * 0.001
        assert engine.total_fees_paid == pytest.approx(expected_entry_fee)

        tp_c = _candle(105, 115, d=date(2024, 1, 16), open_=110, close=110)
        engine.process_day({"HPG": tp_c}, date(2024, 1, 16))

        expected_exit_fees = qty * 110.0 * 0.002
        assert engine.total_fees_paid == pytest.approx(expected_entry_fee + expected_exit_fees)
        summary = engine.compute_summary(date(2024, 1, 1), date(2024, 12, 31))
        assert summary["total_fees_paid"] == pytest.approx(expected_entry_fee + expected_exit_fees)


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


class TestSignalDates:
    def test_sunday_only_includes_previous_sunday_for_partial_first_window(self):
        signal_dates = get_signal_dates(date(2024, 1, 3), date(2024, 1, 15), [6])
        assert signal_dates == [date(2023, 12, 31), date(2024, 1, 7), date(2024, 1, 14)]

    def test_tuesday_thursday_schedule_covers_partial_first_window(self):
        signal_dates = get_signal_dates(date(2024, 1, 3), date(2024, 1, 12), [1, 3])
        assert signal_dates == [date(2024, 1, 2), date(2024, 1, 4), date(2024, 1, 9), date(2024, 1, 11)]

    def test_parse_signal_days_accepts_short_and_long_names(self):
        assert _parse_signal_days("sun,tuesday,thu") == [1, 3, 6]

    def test_parse_signal_days_rejects_unknown_tokens(self):
        with pytest.raises(ValueError, match="Unknown signal day"):
            _parse_signal_days("sun,funday")


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


class TestBuyRanking:
    def test_buy_priority_key_is_deterministic(self):
        recs = [
            Recommendation("BBB", "stock", "BUY", 10, 11, 9, 14, 0.10, entry_price=10),
            Recommendation("AAA", "stock", "BUY", 10, 11, 8, 16, 0.10, entry_price=10),
            Recommendation("CCC", "stock", "BUY", 10, 11, 9, 13, 0.12, entry_price=10),
        ]
        ordered = sorted(recs, key=_buy_priority_key)
        assert [r.symbol for r in ordered] == ["CCC", "BBB", "AAA"]


class TestWatchlistLoading:
    def test_load_watchlist_filters_by_effective_dates(self, tmp_path):
        path = tmp_path / "watchlist.txt"
        path.write_text(
            "HPG from=2024-01-01\n"
            "VNM from=2025-01-01 to=2025-12-31\n"
            "FPT\n"
        )

        assert load_watchlist(str(path), as_of=date(2024, 6, 1)) == ["HPG", "FPT"]
        assert load_watchlist(str(path), as_of=date(2025, 6, 1)) == ["HPG", "VNM", "FPT"]
        assert load_watchlist(str(path), as_of=date(2026, 1, 1)) == ["HPG", "FPT"]

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


class TestPendingEntryPersistence:
    class _Provider:
        def __init__(self, candles_by_symbol):
            self._candles_by_symbol = candles_by_symbol

        def get_daily_history(self, symbol, start, end):
            candles = self._candles_by_symbol.get(symbol, [])
            return [c for c in candles if start <= c.date <= end]

    class _SingleSignalPullbackStrategy:
        def __init__(self, valid_days: int, first_regime: str = "bull", later_regime: str | None = None):
            self.valid_days = valid_days
            self.first_regime = first_regime
            self.later_regime = later_regime or first_regime

        def generate_weekly_plan(self, market_data, portfolio_state, config):
            latest_date = max(c.date for candles in market_data.values() for c in candles)
            is_first_window = latest_date <= date(2023, 12, 29)
            recommendations = []
            if is_first_window:
                recommendations.append(
                    Recommendation(
                        symbol="HPG",
                        asset_class="stock",
                        action="BUY",
                        buy_zone_low=100.0,
                        buy_zone_high=100.0,
                        stop_loss=95.0,
                        take_profit=120.0,
                        position_target_pct=0.10,
                        rationale_bullets=["Test pullback"],
                        entry_type="pullback",
                        entry_price=100.0,
                        entry_valid_for_days=self.valid_days,
                    )
                )
            return WeeklyPlan(
                generated_at="2026-04-12T00:00:00",
                strategy_id="test_strategy",
                strategy_version="test",
                allocation_targets={"stock": 0.9, "bond_fund": 0.1},
                recommendations=recommendations,
                market_regime=self.first_regime if is_first_window else self.later_regime,
                notes=[],
            )

    def _candles(self):
        return [
            _candle(101, 103, d=date(2023, 12, 29), close=102),
            _candle(101, 103, d=date(2024, 1, 1), close=102),
            _candle(101, 103, d=date(2024, 1, 2), close=102),
            _candle(101, 103, d=date(2024, 1, 3), close=102),
            _candle(101, 103, d=date(2024, 1, 4), close=102),
            _candle(101, 103, d=date(2024, 1, 5), close=102),
            _candle(99, 101, d=date(2024, 1, 8), close=100),
            _candle(99, 101, d=date(2024, 1, 9), close=100),
        ]

    def test_pending_pullback_can_persist_into_next_signal_window(self):
        from src.backtest.cli import _run_single

        provider = self._Provider({"HPG": self._candles()})
        strategy = self._SingleSignalPullbackStrategy(valid_days=14)
        engine = _run_single(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 1, 10),
            initial_cash=10_000_000,
            order_size=None,
            trades_per_week=4,
            mode="generate",
            plan_file="",
            tie_breaker="worst",
            exit_mode="tpsl_only",
            provider=provider,
            strategy=strategy,
            risk_config={"execution": {}},
            symbols=["HPG"],
            universe=None,
            signal_days=[6],
        )

        assert len(engine.open_trades) == 1
        assert engine.open_trades[0].symbol == "HPG"

    def test_bear_signal_clears_existing_pending_entries(self):
        from src.backtest.cli import _run_single

        provider = self._Provider({"HPG": self._candles()})
        strategy = self._SingleSignalPullbackStrategy(valid_days=14, first_regime="bull", later_regime="bear")
        engine = _run_single(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 1, 10),
            initial_cash=10_000_000,
            order_size=None,
            trades_per_week=4,
            mode="generate",
            plan_file="",
            tie_breaker="worst",
            exit_mode="tpsl_only",
            provider=provider,
            strategy=strategy,
            risk_config={"execution": {}},
            symbols=["HPG"],
            universe=None,
            signal_days=[6],
        )

        assert len(engine.open_trades) == 0

    def test_clear_pending_entries_flag_clears_existing_pending_entries(self):
        from src.backtest.cli import _run_single

        class PendingClearStrategy(self._SingleSignalPullbackStrategy):
            def generate_weekly_plan(self, market_data, portfolio_state, config):
                plan = super().generate_weekly_plan(market_data, portfolio_state, config)
                latest_date = max(c.date for candles in market_data.values() for c in candles)
                if latest_date > date(2023, 12, 29):
                    plan.market_regime = "sideway"
                    plan.router_state = "temporary_correction"
                    plan.clear_pending_entries = True
                    plan.recommendations = []
                return plan

        provider = self._Provider({"HPG": self._candles()})
        strategy = PendingClearStrategy(valid_days=14)
        engine = _run_single(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 1, 10),
            initial_cash=10_000_000,
            order_size=None,
            trades_per_week=4,
            mode="generate",
            plan_file="",
            tie_breaker="worst",
            exit_mode="tpsl_only",
            provider=provider,
            strategy=strategy,
            risk_config={"execution": {}},
            symbols=["HPG"],
            universe=None,
            signal_days=[6],
        )

        assert len(engine.open_trades) == 0

    def test_defensive_sell_is_ignored_in_tpsl_only_mode(self):
        from src.backtest.cli import _run_single

        class DefensiveExitStrategy:
            def generate_weekly_plan(self, market_data, portfolio_state, config):
                latest_date = max(c.date for candles in market_data.values() for c in candles)
                is_first_window = latest_date <= date(2023, 12, 29)
                if is_first_window:
                    recommendations = [
                        Recommendation(
                            symbol="HPG",
                            asset_class="stock",
                            action="BUY",
                            buy_zone_low=100.0,
                            buy_zone_high=100.0,
                            stop_loss=90.0,
                            take_profit=130.0,
                            position_target_pct=0.50,
                            rationale_bullets=["Initial bull entry"],
                            entry_type="pullback",
                            entry_price=100.0,
                            entry_valid_for_days=7,
                        )
                    ]
                    return WeeklyPlan(
                        generated_at="2026-04-12T00:00:00",
                        strategy_id="test_strategy",
                        strategy_version="test",
                        allocation_targets={"stock": 1.0, "bond_fund": 0.0},
                        recommendations=recommendations,
                        market_regime="bull",
                    )

                return WeeklyPlan(
                    generated_at="2026-04-12T00:00:00",
                    strategy_id="test_strategy",
                    strategy_version="test",
                    allocation_targets={"stock": 0.0, "bond_fund": 1.0},
                    recommendations=[
                        Recommendation(
                            symbol="HPG",
                            asset_class="stock",
                            action="SELL",
                            buy_zone_low=0.0,
                            buy_zone_high=0.0,
                            stop_loss=0.0,
                            take_profit=0.0,
                            position_target_pct=0.0,
                            rationale_bullets=["Defensive liquidation"],
                        )
                    ],
                    market_regime="bear",
                    force_defensive_exits=True,
                )

        candles = [
            _candle(99, 101, d=date(2023, 12, 29), close=100),
            _candle(99, 101, d=date(2024, 1, 1), close=100),
            _candle(102, 104, d=date(2024, 1, 2), close=103),
            _candle(104, 106, d=date(2024, 1, 3), close=105),
            _candle(105, 107, d=date(2024, 1, 4), close=106),
            _candle(106, 108, d=date(2024, 1, 5), close=107),
            _candle(106, 108, d=date(2024, 1, 8), close=107),
            _candle(107, 109, d=date(2024, 1, 9), close=108),
        ]
        provider = self._Provider({"HPG": candles})
        engine = _run_single(
            from_date=date(2024, 1, 1),
            to_date=date(2024, 1, 10),
            initial_cash=10_000_000,
            order_size=None,
            trades_per_week=4,
            mode="generate",
            plan_file="",
            tie_breaker="worst",
            exit_mode="tpsl_only",
            provider=provider,
            strategy=DefensiveExitStrategy(),
            risk_config={"execution": {}},
            symbols=["HPG"],
            universe=None,
            signal_days=[6],
        )

        assert len(engine.open_trades) == 1
        assert len(engine.closed_trades) == 0
