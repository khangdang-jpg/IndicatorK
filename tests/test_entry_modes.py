"""Tests for hybrid-mode entry logic and lookahead safeguards.

Covers:
  1. Engine-level trigger functions: entry_touched, breakout_entry_touched.
  2. breakout_level == highs[-2]  (week T-1's high, NOT week T's high).
  3. Insufficient weekly bars → no BUY generated.
  4. Breakout path fires in T+1 (engine trigger: high >= entry_price).
  5. Pullback path fires on range touch (low <= entry <= high).
  6. entry_price is explicit on Recommendation:
       breakout → breakout_level * (1 + buffer)
       pullback → zone midpoint
  7. SL/TP anchored to entry_price (not zone midpoint separately).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.backtest.engine import (
    BacktestEngine,
    breakout_entry_touched,
    entry_touched,
)
from src.models import OHLCV, PortfolioState
from src.strategies.trend_momentum_atr import (
    TrendMomentumATRStrategy,
    _atr,
    _next_monday,
    _resample_weekly,
    _rsi,
    round_to_step,
)


# ---------------------------------------------------------------------------
# Candle / data factories
# ---------------------------------------------------------------------------

def _candle(
    low: float,
    high: float,
    d: date = date(2024, 6, 3),
    close: float | None = None,
    volume: float = 1_000_000,
) -> OHLCV:
    mid = (low + high) / 2
    return OHLCV(date=d, open=mid, high=high, low=low,
                 close=close if close is not None else mid, volume=volume)


def _make_zigzag_candles(
    n_weeks: int = 37,
    start_price: float = 10_000,
    volume: float = 2_000_000,
) -> list[OHLCV]:
    """Alternating +1.0% / −0.7% weekly returns → RSI ≈ 58.8, trend_up=True.

    n_weeks must be odd so the last week is always an up week (ensures
    close > MA10w in the uptrend).

    Analytical RSI over last 14 weeks (7 up × 1%, 7 down × 0.7%):
        avg_gain / avg_loss ≈ 0.5% / 0.35% = 1.43
        RSI ≈ 58.8  (< 70 not overbought; ≥ 50 qualifies for breakout path)
    """
    assert n_weeks % 2 == 1, "use odd n_weeks so last week is always up"
    candles: list[OHLCV] = []
    price = start_price
    d = date(2024, 1, 1)  # Monday
    for wk in range(n_weeks):
        ret = 0.010 if wk % 2 == 0 else -0.007
        end_price = round(price * (1 + ret), 2)
        for day in range(5):
            frac = (day + 1) / 5
            close_px = round(price + (end_price - price) * frac, 2)
            candles.append(OHLCV(
                date=d,
                open=round(close_px * 0.999, 2),
                high=round(close_px * 1.003, 2),
                low=round(close_px * 0.997, 2),
                close=close_px,
                volume=volume,
            ))
            d += timedelta(days=1)
        d += timedelta(days=2)   # skip weekend
        price = end_price
    return candles


_RISK_CFG = {
    "position": {"max_single_position_pct": 0.15, "max_stock_allocation": 0.60},
    "allocation": {"alloc_mode": "fixed_pct", "fixed_alloc_pct_per_trade": 0.10,
                   "min_alloc_pct": 0.03, "max_alloc_pct": 0.15},
}

_EMPTY_PS = PortfolioState(
    positions={}, cash=0, total_value=0,
    allocation={}, unrealized_pnl=0, realized_pnl=0,
)


def _plan(strategy: TrendMomentumATRStrategy, candles: list[OHLCV]):
    return strategy.generate_weekly_plan({"HPG": candles}, _EMPTY_PS, _RISK_CFG)


def _buys(strategy, candles):
    return [r for r in _plan(strategy, candles).recommendations if r.action == "BUY"]


# ---------------------------------------------------------------------------
# Sanity check: zigzag RSI is in the right range
# ---------------------------------------------------------------------------

def test_zigzag_data_rsi_below_70():
    candles = _make_zigzag_candles()
    w = _resample_weekly(candles)
    closes = [c.close for c in w]
    rsi_val = _rsi(closes, 14)
    assert rsi_val is not None
    assert rsi_val < 70, f"RSI={rsi_val:.1f} — adjust zigzag if this fails"
    assert rsi_val > 50, f"RSI={rsi_val:.1f} — trend should be bullish"


# ---------------------------------------------------------------------------
# 1. Engine-level trigger functions
# ---------------------------------------------------------------------------

class TestEntryTriggers:
    def test_entry_touched_pullback_inside_range(self):
        assert entry_touched(_candle(9500, 10500), 10_000) is True

    def test_entry_touched_gap_up_misses(self):
        """Pullback misses when the daily range is entirely above entry."""
        assert entry_touched(_candle(10_100, 10_500), 10_000) is False

    def test_breakout_fills_even_on_gap_up(self):
        """Breakout requires only high >= entry, so a gap-up still fills."""
        assert breakout_entry_touched(_candle(10_100, 10_500), 10_050) is True

    def test_breakout_not_touched_when_high_below(self):
        assert breakout_entry_touched(_candle(9_800, 9_950), 10_000) is False

    def test_pullback_entry_type_fires_on_range_touch(self):
        engine = BacktestEngine(initial_cash=10_000_000)
        c = _candle(low=9_500, high=10_500, d=date(2024, 6, 3))
        filled = engine.try_enter("HPG", 10_000, 9_000, 11_000, c,
                                  position_target_pct=0.10, entry_type="pullback")
        assert filled is True

    def test_pullback_misses_on_gap_above_entry(self):
        engine = BacktestEngine(initial_cash=10_000_000)
        c = _candle(low=10_100, high=10_500, d=date(2024, 6, 3))
        filled = engine.try_enter("HPG", 10_000, 9_000, 11_000, c,
                                  position_target_pct=0.10, entry_type="pullback")
        assert filled is False

    def test_breakout_entry_type_fills_on_gap_up(self):
        """entry_type='breakout' fills when high >= entry even if low > entry."""
        engine = BacktestEngine(initial_cash=10_000_000)
        c = _candle(low=10_100, high=10_500, d=date(2024, 6, 3))
        filled = engine.try_enter("HPG", 10_050, 9_000, 11_000, c,
                                  position_target_pct=0.10, entry_type="breakout")
        assert filled is True

    def test_breakout_does_not_fill_when_high_below_entry(self):
        engine = BacktestEngine(initial_cash=10_000_000)
        c = _candle(low=9_800, high=9_950, d=date(2024, 6, 3))
        filled = engine.try_enter("HPG", 10_000, 9_000, 11_000, c,
                                  position_target_pct=0.10, entry_type="breakout")
        assert filled is False


# ---------------------------------------------------------------------------
# 2. breakout_level == highs[-2]  (week T-1, not week T)
# ---------------------------------------------------------------------------

class TestBreakoutLevelIsHighsMinus2:
    """Lookahead safeguard: breakout_level must be weekly[-2].high."""

    def _sliced(self, candles):
        """Simulate cli.py's cut-off: data up to (not including) next Monday."""
        last_day = candles[-1].date
        days_to_monday = (7 - last_day.weekday()) % 7 or 7
        next_monday = last_day + timedelta(days=days_to_monday)
        return [c for c in candles if c.date < next_monday]

    def test_breakout_level_equals_highs_minus_2(self):
        """breakout_level on a BUY rec must equal weekly[-2].high."""
        candles = _make_zigzag_candles(n_weeks=37)
        sliced = self._sliced(candles)

        weekly = _resample_weekly(sliced)
        expected = weekly[-2].high  # week T-1's high

        strategy = TrendMomentumATRStrategy(params={"rsi_breakout_min": 0})
        buys = _buys(strategy, sliced)
        breakout_recs = [r for r in buys if r.entry_type == "breakout"]
        assert breakout_recs, "Expected at least one breakout BUY (rsi_min=0)"
        assert breakout_recs[0].breakout_level == pytest.approx(expected, rel=1e-4)

    def test_breakout_level_is_not_highs_minus_1(self):
        """breakout_level must NOT equal weekly[-1].high (that would be lookahead)."""
        candles = _make_zigzag_candles(n_weeks=37)
        sliced = self._sliced(candles)

        weekly = _resample_weekly(sliced)
        wrong_level = weekly[-1].high  # week T's high — forbidden

        strategy = TrendMomentumATRStrategy(params={"rsi_breakout_min": 0})
        buys = _buys(strategy, sliced)
        breakout_recs = [r for r in buys if r.entry_type == "breakout"]
        if breakout_recs:
            assert breakout_recs[0].breakout_level != pytest.approx(wrong_level, rel=1e-4), \
                "breakout_level must use highs[-2] (T-1), not highs[-1] (T = lookahead!)"

    def test_insufficient_bars_produces_no_buy(self):
        """Fewer than ma_long weekly bars must produce no BUY."""
        candles = _make_zigzag_candles(n_weeks=37)
        strategy = TrendMomentumATRStrategy(params={"rsi_breakout_min": 0})
        buys = _buys(strategy, candles[:5])
        assert buys == [], "Should produce no BUY with only a few candles"


# ---------------------------------------------------------------------------
# 3 & 4. T+1 timing: entry fills in T+1, NOT in the confirm week T
# ---------------------------------------------------------------------------

class TestWeekTConfirmEntryInTPlus1:
    """Close confirmation happens at strategy level (week T).
    Engine trigger fires in week T+1: candle.high >= entry_price.
    """

    def test_breakout_fills_on_gap_up_in_t1(self):
        """T+1 candle gaps above entry_price → still fills (high >= entry)."""
        entry_price = 10_050.0
        t1_candle = _candle(low=10_060, high=10_200, d=date(2024, 6, 10))
        assert breakout_entry_touched(t1_candle, entry_price) is True

    def test_breakout_does_not_fill_if_high_below_entry_in_t1(self):
        """T+1 candle that never reaches entry_price must not fill."""
        entry_price = 10_050.0
        t1_candle = _candle(low=9_900, high=10_040, d=date(2024, 6, 10))
        assert breakout_entry_touched(t1_candle, entry_price) is False

    def test_week_t_candle_below_entry_price_is_rejected(self):
        """The confirm week's candle is below entry_price (entry = level*1.001).
        If engine were incorrectly called on week-T candles it would not fill.
        This asserts the timing invariant: engine cannot accidentally fill in T.
        """
        breakout_level = 10_000.0
        entry_price = round(breakout_level * 1.001, 2)  # 10_010.0
        # Week T close confirming: close >= breakout_level, but high < entry_price
        week_t_candle = _candle(low=9_980, high=10_005, close=10_001.0,
                                d=date(2024, 6, 7))
        assert breakout_entry_touched(week_t_candle, entry_price) is False


# ---------------------------------------------------------------------------
# 5. entry_price is explicit on Recommendation
# ---------------------------------------------------------------------------

class TestEntryPriceExplicit:
    def _sliced(self, candles):
        last_day = candles[-1].date
        days_to_monday = (7 - last_day.weekday()) % 7 or 7
        next_monday = last_day + timedelta(days=days_to_monday)
        return [c for c in candles if c.date < next_monday]

    def test_breakout_entry_price_is_breakout_level_times_buffer(self):
        candles = _make_zigzag_candles(n_weeks=37)
        sliced = self._sliced(candles)
        weekly = _resample_weekly(sliced)
        breakout_level = weekly[-2].high

        strategy = TrendMomentumATRStrategy(params={
            "rsi_breakout_min": 0, "entry_buffer_pct": 0.001, "price_tick": 10,
        })
        buys = _buys(strategy, sliced)
        breakout_recs = [r for r in buys if r.entry_type == "breakout"]
        assert breakout_recs
        expected = round_to_step(breakout_level * 1.001, 10)
        assert breakout_recs[0].entry_price == expected

    def test_pullback_entry_price_is_zone_midpoint(self):
        candles = _make_zigzag_candles(n_weeks=37)
        strategy = TrendMomentumATRStrategy(params={"rsi_breakout_min": 100, "price_tick": 10})
        buys = _buys(strategy, candles)
        assert buys
        rec = buys[0]
        assert rec.entry_type == "pullback"
        # entry_price is the step-rounded midpoint of the zone
        expected = round_to_step((rec.buy_zone_low + rec.buy_zone_high) / 2.0, 10)
        assert rec.entry_price == expected

    def test_all_buy_recs_have_positive_entry_price(self):
        candles = _make_zigzag_candles(n_weeks=37)
        strategy = TrendMomentumATRStrategy(params={"rsi_breakout_min": 0})
        buys = _buys(strategy, candles)
        assert buys
        for rec in buys:
            assert rec.entry_price > 0, f"{rec.symbol}: entry_price must be > 0"


# ---------------------------------------------------------------------------
# 6. SL/TP anchored directly to entry_price
# ---------------------------------------------------------------------------

class TestSLTPAnchoredToEntryPrice:
    def _weekly_atr(self, candles):
        w = _resample_weekly(candles)
        return _atr([c.high for c in w], [c.low for c in w], [c.close for c in w], 14)

    def _sliced(self, candles):
        last_day = candles[-1].date
        days_to_monday = (7 - last_day.weekday()) % 7 or 7
        next_monday = last_day + timedelta(days=days_to_monday)
        return [c for c in candles if c.date < next_monday]

    def test_breakout_sl_tp_anchored_to_entry_price(self):
        candles = _make_zigzag_candles(n_weeks=37)
        sliced = self._sliced(candles)
        strategy = TrendMomentumATRStrategy(params={
            "rsi_breakout_min": 0, "atr_stop_mult": 2.0, "atr_target_mult": 1.6,
            "price_tick": 10,
        })
        buys = _buys(strategy, sliced)
        breakout_recs = [r for r in buys if r.entry_type == "breakout"]
        assert breakout_recs
        rec = breakout_recs[0]
        atr_val = self._weekly_atr(sliced)
        # Prices are rounded to nearest 10 VND, so allow ±5 tolerance
        assert rec.stop_loss   == pytest.approx(max(rec.entry_price - 2.0 * atr_val, 0), abs=5)
        assert rec.take_profit == pytest.approx(rec.entry_price + 1.6 * atr_val, abs=5)

    def test_pullback_sl_tp_anchored_to_entry_price(self):
        candles = _make_zigzag_candles(n_weeks=37)
        strategy = TrendMomentumATRStrategy(params={
            "rsi_breakout_min": 100,
            "atr_stop_mult": 2.0, "atr_target_mult": 1.6,
            "price_tick": 10,
        })
        buys = _buys(strategy, candles)
        assert buys
        rec = buys[0]
        atr_val = self._weekly_atr(candles)
        # Prices are rounded to nearest 10 VND, so allow ±5 tolerance
        assert rec.stop_loss   == pytest.approx(max(rec.entry_price - 2.0 * atr_val, 0), abs=5)
        assert rec.take_profit == pytest.approx(rec.entry_price + 1.6 * atr_val, abs=5)

    def test_sl_is_never_negative(self):
        candles = _make_zigzag_candles(n_weeks=37)
        strategy = TrendMomentumATRStrategy(params={
            "rsi_breakout_min": 0, "atr_stop_mult": 999.0,
        })
        buys = _buys(strategy, candles)
        for rec in buys:
            assert rec.stop_loss >= 0, "stop_loss must never be negative"


# ---------------------------------------------------------------------------
# 7. T+1 enforcement via earliest_entry_date in engine
# ---------------------------------------------------------------------------

class TestEarliestEntryDate:
    """Engine must reject candles dated before earliest_entry_date for breakout."""

    def test_breakout_blocked_before_earliest_entry_date(self):
        """A week-T candle (before T+1 Monday) must not fill a breakout entry."""
        engine = BacktestEngine(initial_cash=10_000_000)
        # Friday of week T: high >= entry_price, but date < earliest_entry_date
        week_t_friday = _candle(low=10_050, high=10_200, d=date(2024, 6, 7))
        earliest = date(2024, 6, 10)  # Monday of week T+1
        filled = engine.try_enter(
            "HPG", 10_010, 9_000, 11_000, week_t_friday,
            position_target_pct=0.10, entry_type="breakout",
            earliest_entry_date=earliest,
        )
        assert filled is False

    def test_breakout_fills_on_earliest_entry_date(self):
        """A T+1 Monday candle exactly on earliest_entry_date must fill normally."""
        engine = BacktestEngine(initial_cash=10_000_000)
        t1_monday = _candle(low=10_050, high=10_200, d=date(2024, 6, 10))
        earliest = date(2024, 6, 10)
        filled = engine.try_enter(
            "HPG", 10_010, 9_000, 11_000, t1_monday,
            position_target_pct=0.10, entry_type="breakout",
            earliest_entry_date=earliest,
        )
        assert filled is True

    def test_pullback_not_constrained_by_earliest_entry_date(self):
        """Pullback entries are never blocked — gate is breakout-only."""
        engine = BacktestEngine(initial_cash=10_000_000)
        early_candle = _candle(low=9_500, high=10_500, d=date(2024, 6, 7))
        filled = engine.try_enter(
            "HPG", 10_000, 9_000, 11_000, early_candle,
            position_target_pct=0.10, entry_type="pullback",
            earliest_entry_date=None,
        )
        assert filled is True

    def test_pullback_ignores_earliest_entry_date_even_when_set(self):
        """If earliest_entry_date is accidentally passed for a pullback, it must be ignored."""
        engine = BacktestEngine(initial_cash=10_000_000)
        # Candle date (2025-05-30) is before earliest_entry_date (2025-06-02),
        # but entry_type is "pullback" so the gate must NOT apply.
        c = _candle(low=9_500, high=10_500, d=date(2025, 5, 30))
        filled = engine.try_enter(
            "HPG", 10_000, 9_000, 11_000, c,
            position_target_pct=0.10, entry_type="pullback",
            earliest_entry_date=date(2025, 6, 2),   # should be ignored
        )
        assert filled is True, "pullback must not be blocked by earliest_entry_date"

    def test_breakout_blocked_on_date_before_earliest(self):
        """Breakout on 2025-05-30 must be blocked when earliest_entry_date=2025-06-02."""
        engine = BacktestEngine(initial_cash=10_000_000)
        c = _candle(low=10_050, high=10_200, d=date(2025, 5, 30))
        filled = engine.try_enter(
            "HPG", 10_010, 9_000, 11_000, c,
            position_target_pct=0.10, entry_type="breakout",
            earliest_entry_date=date(2025, 6, 2),
        )
        assert filled is False

    def test_breakout_fills_exactly_on_earliest_entry_date(self):
        """Breakout on 2025-06-02 must fill when earliest_entry_date=2025-06-02."""
        engine = BacktestEngine(initial_cash=10_000_000)
        c = _candle(low=10_050, high=10_200, d=date(2025, 6, 2))
        filled = engine.try_enter(
            "HPG", 10_010, 9_000, 11_000, c,
            position_target_pct=0.10, entry_type="breakout",
            earliest_entry_date=date(2025, 6, 2),
        )
        assert filled is True

    def test_strategy_sets_earliest_entry_date_for_breakout(self):
        """Breakout recs from the strategy must have earliest_entry_date = next Monday."""
        candles = _make_zigzag_candles(n_weeks=37)
        last_day = candles[-1].date
        days_to_monday = (7 - last_day.weekday()) % 7 or 7
        next_monday = last_day + timedelta(days=days_to_monday)
        sliced = [c for c in candles if c.date < next_monday]

        weekly = _resample_weekly(sliced)
        signal_week_end = weekly[-1].date  # Friday of week T
        expected_earliest = _next_monday(signal_week_end)

        strategy = TrendMomentumATRStrategy(params={"rsi_breakout_min": 0})
        buys = _buys(strategy, sliced)
        breakout_recs = [r for r in buys if r.entry_type == "breakout"]
        assert breakout_recs
        rec = breakout_recs[0]
        assert rec.earliest_entry_date == expected_earliest

    def test_strategy_sets_none_earliest_for_pullback(self):
        """Pullback recs must have earliest_entry_date=None."""
        candles = _make_zigzag_candles(n_weeks=37)
        strategy = TrendMomentumATRStrategy(params={"rsi_breakout_min": 100})
        buys = _buys(strategy, candles)
        assert buys
        for rec in buys:
            assert rec.entry_type == "pullback"
            assert rec.earliest_entry_date is None


# ---------------------------------------------------------------------------
# 8. VN price rounding (round_to_step)
# ---------------------------------------------------------------------------

class TestRoundToStep:
    def test_rounds_down_below_half(self):
        assert round_to_step(10_014, 10) == 10_010

    def test_rounds_up_at_half(self):
        assert round_to_step(10_015, 10) == 10_020  # round-half-up

    def test_already_aligned(self):
        assert round_to_step(10_000, 10) == 10_000

    def test_rounds_up_above_half(self):
        assert round_to_step(10_016, 10) == 10_020

    def test_zero_is_zero(self):
        assert round_to_step(0, 10) == 0

    def test_step_100(self):
        assert round_to_step(50_049, 100) == 50_000
        assert round_to_step(50_050, 100) == 50_100

    def test_strategy_prices_are_step_aligned(self):
        """All price fields from the strategy must be multiples of price_tick."""
        candles = _make_zigzag_candles(n_weeks=37)
        strategy = TrendMomentumATRStrategy(params={
            "rsi_breakout_min": 0, "price_tick": 10,
        })
        buys = _buys(strategy, candles)
        assert buys
        for rec in buys:
            for field_name, val in [
                ("buy_zone_low",  rec.buy_zone_low),
                ("buy_zone_high", rec.buy_zone_high),
                ("entry_price",   rec.entry_price),
                ("stop_loss",     rec.stop_loss),
                ("take_profit",   rec.take_profit),
            ]:
                if val > 0:  # skip 0 (SELL take_profit etc.)
                    assert val % 10 == 0, (
                        f"{rec.symbol} {field_name}={val} is not a multiple of 10"
                    )

    def test_buy_zone_high_always_ge_buy_zone_low(self):
        """buy_zone_high must always be >= buy_zone_low, even at large entry_buffer."""
        candles = _make_zigzag_candles(n_weeks=37)
        last_day = candles[-1].date
        days_to_monday = (7 - last_day.weekday()) % 7 or 7
        next_monday = last_day + timedelta(days=days_to_monday)
        sliced = [c for c in candles if c.date < next_monday]

        # Use a large buffer to stress-test the zone ordering
        strategy = TrendMomentumATRStrategy(params={
            "rsi_breakout_min": 0, "entry_buffer_pct": 0.008,
        })
        buys = _buys(strategy, sliced)
        for rec in buys:
            assert rec.buy_zone_high >= rec.buy_zone_low, (
                f"{rec.symbol}: buy_zone_high ({rec.buy_zone_high}) < buy_zone_low ({rec.buy_zone_low})"
            )
