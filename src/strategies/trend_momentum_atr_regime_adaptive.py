"""Regime-Adaptive Trend + Momentum + ATR-based stops strategy.

This strategy adapts parameters based on detected market regime (bull/bear/sideways)
to optimize performance across different market conditions.

Market Regime Detection:
- BEAR: VN-Index downtrend > 5% over 60 days with high volatility
- BULL: VN-Index uptrend > 5% over 60 days with lower volatility
- SIDEWAYS: Mixed conditions or insufficient trend

Regime-Specific Parameters:
- Bear: Very selective (RSI≥65), defensive sizing (6%), tight TP (2.0x ATR)
- Bull: More opportunities (RSI≥45), aggressive sizing (15%), wide TP (4.0x ATR)
- Sideways: Balanced (RSI≥55), moderate sizing (10%), standard TP (2.5x ATR)
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


class TrendMomentumATRRegimeAdaptive(Strategy):
    """Regime-adaptive trend momentum strategy with dynamic parameter adjustment."""

    def __init__(self, params: dict | None = None):
        params = params or {}
        self.ma_short = params.get("ma_short", 10)
        self.ma_long = params.get("ma_long", 30)
        self.rsi_period = params.get("rsi_period", 14)
        self.atr_period = params.get("atr_period", 14)
        self.entry_buffer_pct = float(params.get("entry_buffer_pct", 0.001))
        self.price_tick = params.get("price_tick", None)

        # Regime detection parameters
        self.regime_lookback = params.get("regime_lookback", 60)  # days
        self.trend_threshold = params.get("trend_threshold", 0.05)  # 5%

        # Bear market parameters (defensive)
        self.bear_rsi_threshold = params.get("bear_rsi_threshold", 65)
        self.bear_position_multiplier = params.get("bear_position_multiplier", 0.7)  # 0.7x base allocation
        self.bear_atr_stop_mult = params.get("bear_atr_stop_mult", 1.2)
        self.bear_atr_target_mult = params.get("bear_atr_target_mult", 2.0)

        # Bull market parameters (aggressive)
        self.bull_rsi_threshold = params.get("bull_rsi_threshold", 45)
        self.bull_position_multiplier = params.get("bull_position_multiplier", 1.5)  # 1.5x base allocation
        self.bull_atr_stop_mult = params.get("bull_atr_stop_mult", 1.8)
        self.bull_atr_target_mult = params.get("bull_atr_target_mult", 4.0)

        # Sideways market parameters (balanced)
        self.sideways_rsi_threshold = params.get("sideways_rsi_threshold", 55)
        self.sideways_position_multiplier = params.get("sideways_position_multiplier", 1.0)  # 1.0x base allocation
        self.sideways_atr_stop_mult = params.get("sideways_atr_stop_mult", 1.5)
        self.sideways_atr_target_mult = params.get("sideways_atr_target_mult", 2.5)

        self.current_regime = "sideways"  # Default

    @property
    def id(self) -> str:
        return "trend_momentum_atr_regime_adaptive"

    @property
    def version(self) -> str:
        return "1.0.0"

    def detect_market_regime(self, vnindex_candles: list[OHLCV]) -> str:
        """Detect market regime based on VN-Index trend and volatility.

        Returns:
            'bull', 'bear', or 'sideways'
        """
        if len(vnindex_candles) < self.regime_lookback:
            logger.debug("Insufficient VN-Index data for regime detection, using sideways")
            return "sideways"

        # Get last N days of VN-Index data
        recent = vnindex_candles[-self.regime_lookback:]
        closes = [c.close for c in recent]

        if len(closes) < 20:
            return "sideways"

        # Calculate total return
        start_price = closes[0]
        end_price = closes[-1]
        total_return = (end_price - start_price) / start_price

        # Calculate volatility (std of daily returns, annualized)
        returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
        if len(returns) < 2:
            return "sideways"

        vol_std = _std(returns)
        annualized_vol = vol_std * (252 ** 0.5)  # Annualize daily volatility

        # Regime classification (adjusted for Vietnamese market volatility)
        # Vietnamese stocks naturally have 30-40% volatility even in bull markets
        if total_return > self.trend_threshold and annualized_vol < 0.40:
            regime = "bull"
        elif total_return < -self.trend_threshold:
            regime = "bear"
        elif total_return > 0.08:  # Strong positive return (>8%) suggests bull even if volatile
            regime = "bull"
        else:
            regime = "sideways"

        logger.info(
            "Market regime: %s (return: %.2f%%, vol: %.2f%%)",
            regime.upper(), total_return * 100, annualized_vol * 100
        )

        return regime

    def get_regime_params(self, regime: str) -> dict:
        """Get parameters for the current market regime."""
        params_map = {
            "bull": {
                "rsi_threshold": self.bull_rsi_threshold,
                "position_multiplier": self.bull_position_multiplier,
                "atr_stop_mult": self.bull_atr_stop_mult,
                "atr_target_mult": self.bull_atr_target_mult,
            },
            "bear": {
                "rsi_threshold": self.bear_rsi_threshold,
                "position_multiplier": self.bear_position_multiplier,
                "atr_stop_mult": self.bear_atr_stop_mult,
                "atr_target_mult": self.bear_atr_target_mult,
            },
            "sideways": {
                "rsi_threshold": self.sideways_rsi_threshold,
                "position_multiplier": self.sideways_position_multiplier,
                "atr_stop_mult": self.sideways_atr_stop_mult,
                "atr_target_mult": self.sideways_atr_target_mult,
            },
        }
        return params_map.get(regime, params_map["sideways"])

    def detect_regime_from_universe(self, market_data: dict[str, list[OHLCV]]) -> str:
        """Detect market regime from the stock universe when VN-Index is unavailable.

        Uses the average performance of large-cap stocks as a proxy for market conditions.
        """
        # Use large-cap stocks as market proxy
        proxy_symbols = ["VCB", "VHM", "VIC", "HPG", "VNM", "FPT", "MWG", "GAS", "TCB", "MBB"]

        total_return = 0
        count = 0
        volatilities = []

        for symbol in proxy_symbols:
            candles = market_data.get(symbol, [])
            if not candles or len(candles) < self.regime_lookback:
                continue

            recent = candles[-self.regime_lookback:]
            closes = [c.close for c in recent]

            if len(closes) < 20:
                continue

            # Calculate return
            start_price = closes[0]
            end_price = closes[-1]
            ret = (end_price - start_price) / start_price
            total_return += ret
            count += 1

            # Calculate volatility
            returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
            if len(returns) >= 2:
                vol_std = _std(returns)
                annualized_vol = vol_std * (252 ** 0.5)
                volatilities.append(annualized_vol)

        if count == 0:
            return "sideways"

        avg_return = total_return / count
        avg_vol = sum(volatilities) / len(volatilities) if volatilities else 0.30

        # Regime classification (adjusted for Vietnamese market volatility)
        # Vietnamese stocks naturally have 30-40% volatility even in bull markets
        # Use 40% threshold and add momentum confirmation
        if avg_return > self.trend_threshold and avg_vol < 0.40:
            regime = "bull"
        elif avg_return < -self.trend_threshold:
            regime = "bear"
        elif avg_return > 0.08:  # Strong positive return (>8%) suggests bull even if volatile
            regime = "bull"
        else:
            regime = "sideways"

        logger.info(
            "Market regime (from universe): %s (avg return: %.2f%%, avg vol: %.2f%%)",
            regime.upper(), avg_return * 100, avg_vol * 100
        )

        return regime

    def generate_weekly_plan(
        self,
        market_data: dict[str, list[OHLCV]],
        portfolio_state: PortfolioState,
        config: dict,
    ) -> WeeklyPlan:
        recommendations = []
        held_symbols = set(portfolio_state.positions.keys())
        stock_target = config.get("position", {}).get("max_stock_allocation", 0.60)

        # Detect market regime using VN-Index
        vnindex_candles = market_data.get("VNINDEX") or market_data.get("VNI") or market_data.get("^VNINDEX")
        if vnindex_candles and len(vnindex_candles) >= self.regime_lookback:
            self.current_regime = self.detect_market_regime(vnindex_candles)
        else:
            # Fallback: detect regime from stock universe
            self.current_regime = self.detect_regime_from_universe(market_data)

        # Get regime-specific parameters
        regime_params = self.get_regime_params(self.current_regime)
        rsi_breakout_min = regime_params["rsi_threshold"]
        atr_stop_mult = regime_params["atr_stop_mult"]
        atr_target_mult = regime_params["atr_target_mult"]

        logger.info(
            "Regime: %s | RSI≥%.0f | Position: %.2fx base | SL: %.1fx | TP: %.1fx",
            self.current_regime.upper(),
            rsi_breakout_min,
            regime_params["position_multiplier"],
            atr_stop_mult,
            atr_target_mult,
        )

        for symbol, daily_candles in market_data.items():
            # Skip VN-Index
            if symbol in ["VNINDEX", "VNI"]:
                continue

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

            ma_short = _sma(closes, self.ma_short)
            ma_long_val = _sma(closes, self.ma_long)
            rsi = _rsi(closes, self.rsi_period)
            atr = _atr(highs, lows, closes, self.atr_period)
            vol_avg = _sma(volumes, self.atr_period) if len(volumes) >= self.atr_period else None

            if ma_short is None or ma_long_val is None or atr is None or atr == 0:
                continue

            current = closes[-1]
            is_held = symbol in held_symbols

            trend_up = current > ma_short > ma_long_val
            trend_weakening = current < ma_short and current > ma_long_val
            trend_down = current < ma_long_val

            rsi_overbought = rsi is not None and rsi > 70

            tick = float(self.price_tick) if self.price_tick is not None else vnd_tick_size(current)
            signal_week_end = weekly[-1].date

            if trend_up and not rsi_overbought:
                action = "HOLD" if is_held else "BUY"

                if action == "BUY":
                    # Try close-confirmed breakout first
                    if len(weekly) >= 2:
                        breakout_level = highs[-2]
                        close_confirmed = closes[-1] >= breakout_level
                    else:
                        breakout_level = 0.0
                        close_confirmed = False

                    rsi_ok = rsi is not None and rsi >= rsi_breakout_min
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

                    vol_ratio = volumes[-1] / vol_avg if vol_avg and vol_avg > 0 else 0.0
                    rationale = [
                        f"Regime: {self.current_regime.upper()} | RSI≥{rsi_breakout_min:.0f}",
                        f"Trend UP: price {current:.0f} > MA{self.ma_short}w {ma_short:.0f} > MA{self.ma_long}w {ma_long_val:.0f}",
                        f"RSI({self.rsi_period}): {rsi:.1f}",
                        f"ATR: {atr:.0f}",
                        f"Vol: {volumes[-1]:,.0f} ({vol_ratio:.1f}x avg)" if vol_avg else f"Vol: {volumes[-1]:,.0f}",
                        f"Entry: {'breakout @ T-1 high ' + str(int(breakout_level)) + ' [close-confirmed, T+1]' if entry_type == 'breakout' else 'pullback mid-zone'}",
                    ]

                else:  # HOLD
                    buy_zone_low = round_to_step(current - 1.0 * atr, tick)
                    buy_zone_high = round_to_step(current - 0.5 * atr, tick)
                    entry_price = round_to_step((buy_zone_low + buy_zone_high) / 2.0, tick)
                    breakout_level = 0.0
                    entry_type = "pullback"
                    earliest_entry_date = None
                    rationale = [
                        f"Regime: {self.current_regime.upper()}",
                        f"Trend UP: price {current:.0f} > MA{self.ma_short}w {ma_short:.0f} > MA{self.ma_long}w {ma_long_val:.0f}",
                        f"RSI({self.rsi_period}): {rsi:.1f}",
                        f"ATR: {atr:.0f}",
                    ]

                # Regime-adaptive SL/TP
                stop_loss = round_to_step(entry_price - atr_stop_mult * atr, tick)
                take_profit = round_to_step(entry_price + atr_target_mult * atr, tick)

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
                rationale = [
                    f"Regime: {self.current_regime.upper()}",
                    f"Trend WEAKENING: price {current:.0f} < MA{self.ma_short}w {ma_short:.0f}",
                    f"Still above MA{self.ma_long}w {ma_long_val:.0f}",
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
                rationale = [
                    f"Regime: {self.current_regime.upper()}",
                    f"Trend DOWN: price {current:.0f} < MA{self.ma_long}w {ma_long_val:.0f}",
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
                rationale = [
                    f"Regime: {self.current_regime.upper()}",
                    f"Trend UP but RSI overbought ({rsi:.1f})",
                    "Hold but don't add",
                ]

            else:
                continue

            # Ensure stop_loss is not negative
            stop_loss = max(stop_loss, 0.0)

            # Regime-adaptive position sizing using config + regime multiplier
            if action == "BUY":
                base_alloc = _compute_alloc_pct(config, entry_price, stop_loss)
                regime_multiplier = regime_params["position_multiplier"]
                position_target_pct = _apply_regime_multiplier(base_alloc, regime_multiplier, config)
            else:
                position_target_pct = 0.0

            recommendations.append(Recommendation(
                symbol=symbol,
                asset_class="stock",
                action=action,
                buy_zone_low=buy_zone_low,
                buy_zone_high=buy_zone_high,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_target_pct=position_target_pct,
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
            market_regime=self.current_regime,
            notes=[
                f"Regime-Adaptive Strategy | Current regime: {self.current_regime.upper()}",
                f"MA{self.ma_short}w/MA{self.ma_long}w trend + RSI({self.rsi_period})≥{rsi_breakout_min} momentum",
                f"ATR({self.atr_period})-based stops: {atr_stop_mult:.1f}x stop, {atr_target_mult:.1f}x target",
                f"Position sizing: {regime_params['position_multiplier']:.2f}x base allocation (config-driven)",
            ],
        )


def round_to_step(price: float, step: float = 10.0) -> float:
    """Round price to the nearest step size (round-half-up)."""
    if step <= 0:
        return price
    return float(math.floor(price / step + 0.5) * step)


def _next_monday(d: date) -> date:
    """Return the Monday immediately following date d."""
    days_ahead = (7 - d.weekday()) % 7 or 7
    return d + timedelta(days=days_ahead)


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


def _std(values: list[float]) -> float:
    """Calculate standard deviation."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return variance ** 0.5


def _compute_alloc_pct(config: dict, entry_price: float, sl: float) -> float:
    """Compute base position allocation from risk.yml config.

    fixed_pct mode:  returns fixed_alloc_pct_per_trade (clamped)
    risk_based mode: risk_per_trade_pct / stop_distance_pct (clamped)
    """
    alloc_cfg = config.get("allocation", {})
    mode = alloc_cfg.get("alloc_mode", "fixed_pct")
    lo = alloc_cfg.get("min_alloc_pct", 0.03)
    hi = alloc_cfg.get("max_alloc_pct", 0.15)

    if mode == "risk_based":
        stop_dist = abs(entry_price - sl) / entry_price if entry_price > 0 else 0.0
        if stop_dist < 0.001:  # Avoid division by zero
            raw = alloc_cfg.get("fixed_alloc_pct_per_trade", 0.10)
        else:
            raw = alloc_cfg.get("risk_per_trade_pct", 0.01) / stop_dist
    else:
        raw = alloc_cfg.get("fixed_alloc_pct_per_trade", 0.10)

    return round(max(lo, min(hi, raw)), 4)


def _apply_regime_multiplier(base_alloc: float, multiplier: float, config: dict) -> float:
    """Apply regime multiplier to base allocation and clamp to min/max."""
    alloc_cfg = config.get("allocation", {})
    lo = alloc_cfg.get("min_alloc_pct", 0.03)
    hi = alloc_cfg.get("max_alloc_pct", 0.15)

    adjusted = base_alloc * multiplier
    return round(max(lo, min(hi, adjusted)), 4)
