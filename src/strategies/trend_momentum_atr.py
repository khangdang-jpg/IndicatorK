"""S1: Trend + Momentum + ATR-based stops strategy.

Single entry mode: Hybrid with weekly-close-confirmed breakouts.

For each symbol/week the strategy chooses one of two entry paths:

  BREAKOUT path (close-confirmed, T+1 entry):
    Conditions:
      - strong_trend:    weekly_close > MA10w > MA30w
      - strong_momentum: RSI(14) >= rsi_breakout_min (default 50)
      - close_confirmed: week-T close >= week-(T-1) high  [strategy-level check]
    breakout_level = weekly[-2].high  (week T-1's high — strict no-lookahead)
    entry_price   = breakout_level * (1 + entry_buffer_pct)
    Fills in T+1 when: candle.high >= entry_price

  PULLBACK path (ATR zone, mid-price touch):
    Conditions: trend_up but close-confirmation or RSI threshold not met
    entry_price = midpoint of [current - 1.0*ATR, current - 0.5*ATR]
    Fills when: candle.low <= entry_price <= candle.high

SL/TP are anchored directly to entry_price:
  stop_loss   = entry_price - atr_stop_mult * ATR
  take_profit = entry_price + atr_target_mult * ATR

ATR and all indicators are computed on WEEKLY candles.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import date, datetime, timedelta

from src.models import OHLCV, PortfolioState, Recommendation, WeeklyPlan
from src.strategies.base import Strategy
from src.utils.trading_hours import vnd_tick_size

logger = logging.getLogger(__name__)


class TrendMomentumATRStrategy(Strategy):

    def __init__(self, params: dict | None = None):
        params = params or {}
        self.ma_short        = params.get("ma_short", 10)
        self.ma_long         = params.get("ma_long", 30)
        self.rsi_period      = params.get("rsi_period", 14)
        self.atr_period      = params.get("atr_period", 14)
        self.atr_stop_mult   = params.get("atr_stop_mult", 1.5)
        self.atr_target_mult = params.get("atr_target_mult", 2.0)
        # RSI must be >= this to qualify for the breakout path
        self.rsi_breakout_min = float(params.get("rsi_breakout_min", 50))
        # Small buffer above breakout_level for the entry_price
        self.entry_buffer_pct = float(params.get("entry_buffer_pct", 0.001))
        # VN price tick size — all output prices are rounded to this step
        self.price_tick = float(params.get("price_tick", 10))

    @property
    def id(self) -> str:
        return "trend_momentum_atr"

    @property
    def version(self) -> str:
        return "2.0.0"

    def generate_weekly_plan(
        self,
        market_data: dict[str, list[OHLCV]],
        portfolio_state: PortfolioState,
        config: dict,
    ) -> WeeklyPlan:
        recommendations = []
        held_symbols = set(portfolio_state.positions.keys())
        stock_target = config.get("position", {}).get("max_stock_allocation", 0.60)

        for symbol, daily_candles in market_data.items():
            if len(daily_candles) < self.ma_long + 5:
                logger.info("Skipping %s: not enough data (%d candles)", symbol, len(daily_candles))
                continue

            weekly = _resample_weekly(daily_candles)
            if len(weekly) < self.ma_long:
                continue

            closes  = [c.close for c in weekly]
            highs   = [c.high  for c in weekly]
            lows    = [c.low   for c in weekly]
            volumes = [c.volume for c in weekly]

            ma_short    = _sma(closes, self.ma_short)
            ma_long_val = _sma(closes, self.ma_long)
            rsi         = _rsi(closes, self.rsi_period)
            atr         = _atr(highs, lows, closes, self.atr_period)
            vol_avg     = _sma(volumes, self.atr_period) if len(volumes) >= self.atr_period else None

            if ma_short is None or ma_long_val is None or atr is None or atr == 0:
                continue

            current = closes[-1]
            is_held = symbol in held_symbols

            trend_up        = current > ma_short > ma_long_val
            trend_weakening = current < ma_short and current > ma_long_val
            trend_down      = current < ma_long_val

            rsi_overbought = rsi is not None and rsi > 70

            tick = vnd_tick_size(current)
            signal_week_end = weekly[-1].date  # Friday of week T

            if trend_up and not rsi_overbought:
                action = "HOLD" if is_held else "BUY"

                if action == "BUY":
                    # ── Hybrid: try close-confirmed breakout first ────────────
                    # breakout_level = week T-1's high (highs[-2]).
                    # cli.py passes data cut to c.date < week_start, so:
                    #   weekly[-1] = week T (last complete week)
                    #   weekly[-2] = week T-1 (the reference)
                    # Close confirmation is done HERE at the strategy level —
                    # the engine only needs candle.high >= entry_price in T+1.
                    if len(weekly) >= 2:
                        breakout_level  = highs[-2]         # week T-1 high
                        close_confirmed = closes[-1] >= breakout_level
                    else:
                        breakout_level  = 0.0
                        close_confirmed = False

                    rsi_ok = rsi is not None and rsi >= self.rsi_breakout_min
                    # Volume confirmation: current week volume must exceed average
                    vol_ok = vol_avg is not None and vol_avg > 0 and volumes[-1] >= vol_avg

                    if close_confirmed and rsi_ok and vol_ok:
                        # Breakout: entry above breakout_level in T+1
                        entry_price   = round_to_step(breakout_level * (1.0 + self.entry_buffer_pct), tick)
                        buy_zone_low  = entry_price
                        # buy_zone_high always >= buy_zone_low (relative to entry_price)
                        buy_zone_high = round_to_step(entry_price * 1.005, tick)
                        entry_type    = "breakout"
                        # T+1 enforcement: earliest fill = Monday of next week
                        earliest_entry_date = _next_monday(signal_week_end)
                    else:
                        # Pullback: entry in the ATR mid-zone
                        buy_zone_low  = round_to_step(current - 1.0 * atr, tick)
                        buy_zone_high = round_to_step(current - 0.5 * atr, tick)
                        entry_price   = round_to_step((buy_zone_low + buy_zone_high) / 2.0, tick)
                        breakout_level = 0.0
                        entry_type    = "pullback"
                        earliest_entry_date = None

                    vol_ratio = volumes[-1] / vol_avg if vol_avg and vol_avg > 0 else 0.0
                    rationale = [
                        f"Trend UP: price {current:.0f} > MA{self.ma_short}w {ma_short:.0f} > MA{self.ma_long}w {ma_long_val:.0f}",
                        f"RSI({self.rsi_period}): {rsi:.1f}",
                        f"ATR: {atr:.0f}",
                        f"Vol: {volumes[-1]:,.0f} ({vol_ratio:.1f}x avg)" if vol_avg else f"Vol: {volumes[-1]:,.0f}",
                        f"Entry: {'breakout @ T-1 high ' + str(int(breakout_level)) + ' [close-confirmed, T+1]' if entry_type == 'breakout' else 'pullback mid-zone'}",
                    ]

                else:  # HOLD — reference zone only, not used for fills
                    buy_zone_low        = round_to_step(current - 1.0 * atr, tick)
                    buy_zone_high       = round_to_step(current - 0.5 * atr, tick)
                    entry_price         = round_to_step((buy_zone_low + buy_zone_high) / 2.0, tick)
                    breakout_level      = 0.0
                    entry_type          = "pullback"
                    earliest_entry_date = None
                    rationale = [
                        f"Trend UP: price {current:.0f} > MA{self.ma_short}w {ma_short:.0f} > MA{self.ma_long}w {ma_long_val:.0f}",
                        f"RSI({self.rsi_period}): {rsi:.1f}",
                        f"ATR: {atr:.0f}",
                    ]

                # SL/TP anchored to entry_price
                stop_loss   = round_to_step(entry_price - self.atr_stop_mult  * atr, tick)
                take_profit = round_to_step(entry_price + self.atr_target_mult * atr, tick)

            elif trend_weakening and is_held:
                action              = "REDUCE"
                buy_zone_low        = round_to_step(current - 1.5 * atr, tick)
                buy_zone_high       = round_to_step(current - 1.0 * atr, tick)
                entry_price         = round_to_step((buy_zone_low + buy_zone_high) / 2.0, tick)
                stop_loss           = round_to_step(entry_price - 2.0 * atr, tick)
                take_profit         = round_to_step(entry_price + 1.0 * atr, tick)
                breakout_level      = 0.0
                entry_type          = "pullback"
                earliest_entry_date = None
                rationale = [
                    f"Trend WEAKENING: price {current:.0f} < MA{self.ma_short}w {ma_short:.0f}",
                    f"Still above MA{self.ma_long}w {ma_long_val:.0f}",
                    "Consider reducing position",
                ]

            elif trend_down and is_held:
                action              = "SELL"
                buy_zone_low        = 0
                buy_zone_high       = 0
                entry_price         = 0.0
                stop_loss           = round_to_step(current - 1.0 * atr, tick)
                take_profit         = 0
                breakout_level      = 0.0
                entry_type          = "pullback"
                earliest_entry_date = None
                rationale = [
                    f"Trend DOWN: price {current:.0f} < MA{self.ma_long}w {ma_long_val:.0f}",
                    "Exit position",
                ]

            elif trend_up and rsi_overbought and is_held:
                action              = "HOLD"
                buy_zone_low        = round_to_step(current - 1.5 * atr, tick)
                buy_zone_high       = round_to_step(current - 1.0 * atr, tick)
                entry_price         = round_to_step((buy_zone_low + buy_zone_high) / 2.0, tick)
                stop_loss           = round_to_step(entry_price - 2.0 * atr, tick)
                take_profit         = round_to_step(entry_price + 1.5 * atr, tick)
                breakout_level      = 0.0
                entry_type          = "pullback"
                earliest_entry_date = None
                rationale = [
                    f"Trend UP but RSI overbought ({rsi:.1f})",
                    "Hold but don't add",
                ]

            else:
                continue

            # Ensure stop_loss is not negative
            stop_loss = max(stop_loss, 0.0)

            recommendations.append(Recommendation(
                symbol=symbol,
                asset_class="stock",
                action=action,
                buy_zone_low=buy_zone_low,
                buy_zone_high=buy_zone_high,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_target_pct=(
                    _compute_alloc_pct(config, entry_price, stop_loss)
                    if action == "BUY" else 0.0
                ),
                rationale_bullets=rationale,
                entry_type=entry_type,
                breakout_level=breakout_level,
                entry_price=entry_price,
                signal_week_end=signal_week_end,
                earliest_entry_date=earliest_entry_date,
            ))

        # Sort: BUY first, then HOLD, then REDUCE/SELL
        action_order = {"BUY": 0, "HOLD": 1, "REDUCE": 2, "SELL": 3}
        recommendations.sort(key=lambda r: action_order.get(r.action, 99))

        return WeeklyPlan(
            generated_at=datetime.utcnow().isoformat(),
            strategy_id=self.id,
            strategy_version=self.version,
            allocation_targets={"stock": stock_target, "bond_fund": 1.0 - stock_target},
            recommendations=recommendations[:20],
            notes=[
                f"MA{self.ma_short}w/MA{self.ma_long}w trend + RSI({self.rsi_period}) momentum",
                f"ATR({self.atr_period})-based stops: {self.atr_stop_mult}x stop, {self.atr_target_mult}x target",
                f"Hybrid: breakout(weekly-close-confirmed) or pullback; buffer={self.entry_buffer_pct}",
            ],
        )


def round_to_step(price: float, step: float = 10.0) -> float:
    """Round price to the nearest step size (round-half-up).

    Default step = 10 VND (configurable via price_tick in strategy params).

    Examples (step=10):
        10_014 → 10_010
        10_015 → 10_020   (round half up)
        10_055 → 10_060
    """
    if step <= 0:
        return price
    return float(math.floor(price / step + 0.5) * step)


def _next_monday(d: date) -> date:
    """Return the Monday immediately following date d.

    For any weekday: advances to the next Monday.
    If d is already Monday, returns d + 7 (the *next* Monday, not today).
    """
    days_ahead = (7 - d.weekday()) % 7 or 7
    return d + timedelta(days=days_ahead)


def _compute_alloc_pct(config: dict, entry_price: float, sl: float) -> float:
    """Compute position_target_pct from risk.yml allocation config.

    fixed_pct mode:  returns fixed_alloc_pct_per_trade (clamped)
    risk_based mode: risk_per_trade_pct / stop_distance_pct  (clamped)
    """
    alloc_cfg = config.get("allocation", {})
    mode = alloc_cfg.get("alloc_mode", "fixed_pct")
    lo = alloc_cfg.get("min_alloc_pct", 0.03)
    hi = alloc_cfg.get("max_alloc_pct", 0.15)

    if mode == "risk_based":
        stop_dist = abs(entry_price - sl) / entry_price if entry_price > 0 else 0.0
        if stop_dist <= 0:
            raw = alloc_cfg.get("fixed_alloc_pct_per_trade", 0.10)
        else:
            raw = alloc_cfg.get("risk_per_trade_pct", 0.01) / stop_dist
    else:
        raw = alloc_cfg.get("fixed_alloc_pct_per_trade", 0.10)

    return round(max(lo, min(hi, raw)), 4)


def _resample_weekly(daily: list[OHLCV]) -> list[OHLCV]:
    """Resample daily OHLCV into weekly (Mon-Sun) candles."""
    weeks: dict[str, list[OHLCV]] = defaultdict(list)
    for candle in daily:
        yr, wk, _ = candle.date.isocalendar()
        key = f"{yr}-W{wk:02d}"
        weeks[key].append(candle)

    result = []
    for key in sorted(weeks.keys()):
        candles = weeks[key]
        candles.sort(key=lambda c: c.date)
        result.append(OHLCV(
            date=candles[-1].date,
            open=candles[0].open,
            high=max(c.high for c in candles),
            low=min(c.low for c in candles),
            close=candles[-1].close,
            volume=sum(c.volume for c in candles),
        ))
    return result


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _rsi(closes: list[float], period: int) -> float | None:
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(
    highs: list[float], lows: list[float], closes: list[float], period: int
) -> float | None:
    if len(highs) < period + 1:
        return None
    trs = []
    for i in range(-period, 0):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    return sum(trs) / period
