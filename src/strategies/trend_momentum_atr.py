"""S1: Trend + Momentum + ATR-based stops strategy."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

from src.models import OHLCV, PortfolioState, Recommendation, WeeklyPlan
from src.strategies.base import Strategy

logger = logging.getLogger(__name__)


class TrendMomentumATRStrategy(Strategy):

    def __init__(self, params: dict | None = None):
        params = params or {}
        self.ma_short = params.get("ma_short", 10)
        self.ma_long = params.get("ma_long", 30)
        self.rsi_period = params.get("rsi_period", 14)
        self.atr_period = params.get("atr_period", 14)
        self.atr_stop_mult = params.get("atr_stop_mult", 1.5)
        self.atr_target_mult = params.get("atr_target_mult", 2.0)

    @property
    def id(self) -> str:
        return "trend_momentum_atr"

    @property
    def version(self) -> str:
        return "1.0.0"

    def generate_weekly_plan(
        self,
        market_data: dict[str, list[OHLCV]],
        portfolio_state: PortfolioState,
        config: dict,
    ) -> WeeklyPlan:
        recommendations = []
        held_symbols = set(portfolio_state.positions.keys())
        max_pos_pct = config.get("position", {}).get("max_single_position_pct", 0.15)
        stock_target = config.get("position", {}).get("max_stock_allocation", 0.60)

        for symbol, daily_candles in market_data.items():
            if len(daily_candles) < self.ma_long + 5:
                logger.info("Skipping %s: not enough data (%d candles)", symbol, len(daily_candles))
                continue

            weekly = _resample_weekly(daily_candles)
            if len(weekly) < self.ma_long:
                continue

            closes = [c.close for c in weekly]
            highs = [c.high for c in weekly]
            lows = [c.low for c in weekly]

            ma_short = _sma(closes, self.ma_short)
            ma_long_val = _sma(closes, self.ma_long)
            rsi = _rsi(closes, self.rsi_period)
            atr = _atr(highs, lows, closes, self.atr_period)

            if ma_short is None or ma_long_val is None or atr is None or atr == 0:
                continue

            current = closes[-1]
            is_held = symbol in held_symbols

            trend_up = current > ma_short > ma_long_val
            trend_weakening = current < ma_short and current > ma_long_val
            trend_down = current < ma_long_val

            rsi_bullish = rsi is not None and rsi > 50
            rsi_overbought = rsi is not None and rsi > 70

            if trend_up and not rsi_overbought:
                action = "HOLD" if is_held else "BUY"
                buy_zone_low = round(current - 1.0 * atr, 2)
                buy_zone_high = round(current - 0.5 * atr, 2)
                stop_loss = round(buy_zone_low - self.atr_stop_mult * atr, 2)
                take_profit = round(current + self.atr_target_mult * atr, 2)
                rationale = [
                    f"Trend UP: price {current:.0f} > MA{self.ma_short}w {ma_short:.0f} > MA{self.ma_long}w {ma_long_val:.0f}",
                    f"RSI({self.rsi_period}): {rsi:.1f}",
                    f"ATR: {atr:.0f}",
                ]
            elif trend_weakening and is_held:
                action = "REDUCE"
                buy_zone_low = round(current - 1.5 * atr, 2)
                buy_zone_high = round(current - 1.0 * atr, 2)
                stop_loss = round(current - 2.0 * atr, 2)
                take_profit = round(current + 1.0 * atr, 2)
                rationale = [
                    f"Trend WEAKENING: price {current:.0f} < MA{self.ma_short}w {ma_short:.0f}",
                    f"Still above MA{self.ma_long}w {ma_long_val:.0f}",
                    "Consider reducing position",
                ]
            elif trend_down and is_held:
                action = "SELL"
                buy_zone_low = 0
                buy_zone_high = 0
                stop_loss = round(current - 1.0 * atr, 2)
                take_profit = 0
                rationale = [
                    f"Trend DOWN: price {current:.0f} < MA{self.ma_long}w {ma_long_val:.0f}",
                    "Exit position",
                ]
            elif trend_up and rsi_overbought and is_held:
                action = "HOLD"
                buy_zone_low = round(current - 1.5 * atr, 2)
                buy_zone_high = round(current - 1.0 * atr, 2)
                stop_loss = round(current - 2.0 * atr, 2)
                take_profit = round(current + 1.5 * atr, 2)
                rationale = [
                    f"Trend UP but RSI overbought ({rsi:.1f})",
                    "Hold but don't add",
                ]
            else:
                continue

            # Ensure stop_loss is not negative
            stop_loss = max(stop_loss, 0)

            recommendations.append(Recommendation(
                symbol=symbol,
                asset_class="stock",
                action=action,
                buy_zone_low=buy_zone_low,
                buy_zone_high=buy_zone_high,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_target_pct=max_pos_pct if action == "BUY" else 0,
                rationale_bullets=rationale,
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
            ],
        )


def _resample_weekly(daily: list[OHLCV]) -> list[OHLCV]:
    """Resample daily OHLCV into weekly (Mon-Sun) candles."""
    weeks: dict[str, list[OHLCV]] = defaultdict(list)
    for candle in daily:
        # ISO week key
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
