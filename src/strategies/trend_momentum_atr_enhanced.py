"""S1 Enhanced: Trend Strength Scoring with Dynamic Position Sizing.

This is an enhanced version of trend_momentum_atr.py with:
1. Multi-factor trend strength scoring (0-100 scale)
2. Dynamic position sizing based on trend strength
3. Optional ADX-based regime detection
4. Volume-weighted trend confirmation (already in base strategy)

Trend Strength Score Components:
- Price above MA10w: +25 points
- MA10w above MA30w: +25 points
- RSI momentum: +15 points (RSI > 50)
- ADX trend strength: +15 points (ADX > 25)
- Volume confirmation: +10 points (vol > avg)
- MA10w slope: +10 points (upward slope)

Position Sizing:
- Strong trend (score >= 80): 12-15% per position
- Moderate trend (score 60-79): 10% per position
- Weak trend (score < 60): Skip entry or 8% per position

Usage:
    config/strategy.yml:
        active: trend_momentum_atr_enhanced
        trend_momentum_atr_enhanced:
          ma_short: 10
          ma_long: 30
          trend_score_min: 60  # minimum score to enter
          strong_trend_threshold: 80
          position_strong: 0.12  # 12% for strong trends
          position_moderate: 0.10  # 10% for moderate
          position_weak: 0.08  # 8% for weak (if enabled)
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


class TrendMomentumATREnhanced(Strategy):

    def __init__(self, params: dict | None = None):
        params = params or {}
        self.ma_short = params.get("ma_short", 10)
        self.ma_long = params.get("ma_long", 30)
        self.rsi_period = params.get("rsi_period", 14)
        self.atr_period = params.get("atr_period", 14)
        self.adx_period = params.get("adx_period", 14)  # NEW: ADX for trend strength
        self.atr_stop_mult = params.get("atr_stop_mult", 1.5)
        self.atr_target_mult = params.get("atr_target_mult", 2.5)
        self.rsi_breakout_min = float(params.get("rsi_breakout_min", 50))
        self.entry_buffer_pct = float(params.get("entry_buffer_pct", 0.001))
        self.price_tick = params.get("price_tick", None)

        # NEW: Trend scoring parameters
        self.trend_score_min = params.get("trend_score_min", 60)  # minimum score to enter
        self.strong_trend_threshold = params.get("strong_trend_threshold", 80)
        self.moderate_trend_threshold = params.get("moderate_trend_threshold", 60)

        # NEW: Dynamic position sizing
        self.position_strong = params.get("position_strong", 0.12)  # 12% for strong trends
        self.position_moderate = params.get("position_moderate", 0.10)  # 10% for moderate
        self.position_weak = params.get("position_weak", 0.08)  # 8% for weak trends

        # Enable/disable ADX calculation (computationally expensive)
        self.use_adx = params.get("use_adx", False)

    @property
    def id(self) -> str:
        return "trend_momentum_atr_enhanced"

    @property
    def version(self) -> str:
        return "3.0.0"

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
                logger.debug("Skipping %s: not enough data (%d candles)", symbol, len(daily_candles))
                continue

            weekly = _resample_weekly(daily_candles)
            if len(weekly) < self.ma_long:
                continue

            closes = [c.close for c in weekly]
            highs = [c.high for c in weekly]
            lows = [c.low for c in weekly]
            volumes = [c.volume for c in weekly]

            ma_short_val = _sma(closes, self.ma_short)
            ma_long_val = _sma(closes, self.ma_long)
            rsi = _rsi(closes, self.rsi_period)
            atr = _atr(highs, lows, closes, self.atr_period)
            vol_avg = _sma(volumes, self.atr_period) if len(volumes) >= self.atr_period else None

            if ma_short_val is None or ma_long_val is None or atr is None or atr == 0:
                continue

            # ADX calculation (optional, expensive)
            adx = _adx(highs, lows, closes, self.adx_period) if self.use_adx else None

            current = closes[-1]
            is_held = symbol in held_symbols

            # ══════════════════════════════════════════════════════════════════
            # TREND STRENGTH SCORING SYSTEM (0-100 scale)
            # ══════════════════════════════════════════════════════════════════
            trend_score = 0
            score_breakdown = []

            # Component 1: Price above MA10w (25 points)
            if current > ma_short_val:
                trend_score += 25
                score_breakdown.append("price>MA10w (+25)")

            # Component 2: MA10w above MA30w (25 points)
            if ma_short_val > ma_long_val:
                trend_score += 25
                score_breakdown.append("MA10w>MA30w (+25)")

            # Component 3: RSI momentum (15 points)
            if rsi is not None and rsi >= 50:
                trend_score += 15
                score_breakdown.append(f"RSI={rsi:.0f} (+15)")

            # Component 4: ADX trend strength (15 points) - optional
            if self.use_adx and adx is not None and adx >= 25:
                trend_score += 15
                score_breakdown.append(f"ADX={adx:.0f} (+15)")
            elif not self.use_adx:
                # If ADX disabled, redistribute 15 points proportionally to other components
                # Give bonus to price/MA alignment (already strong indicators)
                if current > ma_short_val > ma_long_val:
                    trend_score += 10
                    score_breakdown.append("strong_alignment (+10)")

            # Component 5: Volume confirmation (10 points)
            vol_ratio = volumes[-1] / vol_avg if vol_avg and vol_avg > 0 else 0.0
            if vol_ratio >= 1.0:
                trend_score += 10
                score_breakdown.append(f"vol={vol_ratio:.1f}x (+10)")

            # Component 6: MA10w slope (10 points)
            if len(closes) >= self.ma_short + 5:
                ma_short_5w_ago = _sma(closes[:-5], self.ma_short)
                if ma_short_5w_ago and ma_short_val > ma_short_5w_ago * 1.02:  # 2% upward slope
                    trend_score += 10
                    score_breakdown.append("MA10w_upslope (+10)")

            # ══════════════════════════════════════════════════════════════════
            # DECISION LOGIC: Use trend score to determine action and position size
            # ══════════════════════════════════════════════════════════════════
            trend_up = trend_score >= self.trend_score_min
            trend_weakening = self.moderate_trend_threshold <= trend_score < self.strong_trend_threshold and current < ma_short_val
            trend_down = trend_score < self.trend_score_min

            rsi_overbought = rsi is not None and rsi > 70

            tick = float(self.price_tick) if self.price_tick is not None else vnd_tick_size(current)
            signal_week_end = weekly[-1].date

            if trend_up and not rsi_overbought:
                action = "HOLD" if is_held else "BUY"

                if action == "BUY":
                    # Entry path selection (same as base strategy)
                    if len(weekly) >= 2:
                        breakout_level = highs[-2]
                        close_confirmed = closes[-1] >= breakout_level
                    else:
                        breakout_level = 0.0
                        close_confirmed = False

                    rsi_ok = rsi is not None and rsi >= self.rsi_breakout_min
                    vol_ok = vol_avg is not None and vol_avg > 0 and volumes[-1] >= vol_avg

                    if close_confirmed and rsi_ok and vol_ok:
                        # Breakout entry
                        entry_price = round_to_step(breakout_level * (1.0 + self.entry_buffer_pct), tick)
                        buy_zone_low = entry_price
                        buy_zone_high = round_to_step(entry_price * 1.005, tick)
                        entry_type = "breakout"
                        earliest_entry_date = _next_monday(signal_week_end)
                    else:
                        # Pullback entry
                        buy_zone_low = round_to_step(current - 1.0 * atr, tick)
                        buy_zone_high = round_to_step(current - 0.5 * atr, tick)
                        entry_price = round_to_step((buy_zone_low + buy_zone_high) / 2.0, tick)
                        breakout_level = 0.0
                        entry_type = "pullback"
                        earliest_entry_date = None

                    # ═══════════════════════════════════════════════════════════
                    # DYNAMIC POSITION SIZING based on trend strength
                    # ═══════════════════════════════════════════════════════════
                    if trend_score >= self.strong_trend_threshold:
                        position_pct = self.position_strong
                        strength_label = "STRONG"
                    elif trend_score >= self.moderate_trend_threshold:
                        position_pct = self.position_moderate
                        strength_label = "MODERATE"
                    else:
                        position_pct = self.position_weak
                        strength_label = "WEAK"

                    rationale = [
                        f"Trend Score: {trend_score}/100 ({strength_label})",
                        f"  Breakdown: {', '.join(score_breakdown)}",
                        f"Position Size: {position_pct*100:.0f}% (trend-based)",
                        f"RSI: {rsi:.1f}, ATR: {atr:.0f}",
                        f"Vol: {volumes[-1]:,.0f} ({vol_ratio:.1f}x)" if vol_avg else f"Vol: {volumes[-1]:,.0f}",
                        f"Entry: {entry_type}",
                    ]

                else:  # HOLD
                    buy_zone_low = round_to_step(current - 1.0 * atr, tick)
                    buy_zone_high = round_to_step(current - 0.5 * atr, tick)
                    entry_price = round_to_step((buy_zone_low + buy_zone_high) / 2.0, tick)
                    breakout_level = 0.0
                    entry_type = "pullback"
                    earliest_entry_date = None
                    position_pct = 0.0
                    rationale = [
                        f"Trend Score: {trend_score}/100 - HOLDING",
                        f"  {', '.join(score_breakdown)}",
                    ]

                # SL/TP anchored to entry_price
                stop_loss = round_to_step(entry_price - self.atr_stop_mult * atr, tick)
                take_profit = round_to_step(entry_price + self.atr_target_mult * atr, tick)

            elif trend_weakening and is_held:
                action = "REDUCE"
                buy_zone_low = round_to_step(current - 1.5 * atr, tick)
                buy_zone_high = round_to_step(current - 1.0 * atr, tick)
                entry_price = round_to_step((buy_zone_low + buy_zone_high) / 2.0, tick)
                stop_loss = round_to_step(entry_price - 2.0 * atr, tick)
                take_profit = round_to_step(entry_price + 1.0 * atr, tick)
                breakout_level = 0.0
                entry_type = "pullback"
                earliest_entry_date = None
                position_pct = 0.0
                rationale = [
                    f"Trend Score: {trend_score}/100 - WEAKENING",
                    "Consider reducing position",
                ]

            elif trend_down and is_held:
                action = "SELL"
                buy_zone_low = 0
                buy_zone_high = 0
                entry_price = 0.0
                stop_loss = round_to_step(current - 1.0 * atr, tick)
                take_profit = 0
                breakout_level = 0.0
                entry_type = "pullback"
                earliest_entry_date = None
                position_pct = 0.0
                rationale = [
                    f"Trend Score: {trend_score}/100 - TREND DOWN",
                    "Exit position",
                ]

            elif trend_up and rsi_overbought and is_held:
                action = "HOLD"
                buy_zone_low = round_to_step(current - 1.5 * atr, tick)
                buy_zone_high = round_to_step(current - 1.0 * atr, tick)
                entry_price = round_to_step((buy_zone_low + buy_zone_high) / 2.0, tick)
                stop_loss = round_to_step(entry_price - 2.0 * atr, tick)
                take_profit = round_to_step(entry_price + 1.5 * atr, tick)
                breakout_level = 0.0
                entry_type = "pullback"
                earliest_entry_date = None
                position_pct = 0.0
                rationale = [
                    f"Trend Score: {trend_score}/100 but RSI overbought ({rsi:.1f})",
                    "Hold but don't add",
                ]

            else:
                continue

            stop_loss = max(stop_loss, 0.0)

            recommendations.append(Recommendation(
                symbol=symbol,
                asset_class="stock",
                action=action,
                buy_zone_low=buy_zone_low,
                buy_zone_high=buy_zone_high,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_target_pct=position_pct,
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
                f"Enhanced trend scoring: multi-factor (0-100 scale), min_score={self.trend_score_min}",
                f"Dynamic position sizing: strong={self.position_strong*100:.0f}%, moderate={self.position_moderate*100:.0f}%",
                f"ATR-based stops: {self.atr_stop_mult}x stop, {self.atr_target_mult}x target",
            ],
        )


# ═══════════════════════════════════════════════════════════════════════════
# Helper functions (reused from base strategy)
# ═══════════════════════════════════════════════════════════════════════════

def round_to_step(price: float, step: float = 10.0) -> float:
    if step <= 0:
        return price
    return float(math.floor(price / step + 0.5) * step)


def _next_monday(d: date) -> date:
    days_ahead = (7 - d.weekday()) % 7 or 7
    return d + timedelta(days=days_ahead)


def _resample_weekly(daily: list[OHLCV]) -> list[OHLCV]:
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


def _adx(
    highs: list[float], lows: list[float], closes: list[float], period: int
) -> float | None:
    """Calculate Average Directional Index (ADX) - trend strength indicator.

    ADX measures trend strength on 0-100 scale:
    - ADX < 20: weak/no trend
    - ADX 20-25: emerging trend
    - ADX 25-50: strong trend
    - ADX > 50: very strong trend

    Note: ADX is computationally expensive, use sparingly.
    """
    if len(highs) < period + 1:
        return None

    # Calculate +DM and -DM
    plus_dm = []
    minus_dm = []
    for i in range(-period, 0):
        high_diff = highs[i] - highs[i - 1]
        low_diff = lows[i - 1] - lows[i]

        if high_diff > low_diff and high_diff > 0:
            plus_dm.append(high_diff)
            minus_dm.append(0)
        elif low_diff > high_diff and low_diff > 0:
            plus_dm.append(0)
            minus_dm.append(low_diff)
        else:
            plus_dm.append(0)
            minus_dm.append(0)

    # Calculate ATR for smoothing
    atr_val = _atr(highs, lows, closes, period)
    if atr_val is None or atr_val == 0:
        return None

    # Calculate +DI and -DI
    plus_di = (sum(plus_dm) / period) / atr_val * 100
    minus_di = (sum(minus_dm) / period) / atr_val * 100

    # Calculate DX
    if plus_di + minus_di == 0:
        return 0.0

    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100

    # ADX is smoothed DX (simplified: using current DX as ADX approximation)
    # For full accuracy, would need to smooth DX over multiple periods
    return dx
