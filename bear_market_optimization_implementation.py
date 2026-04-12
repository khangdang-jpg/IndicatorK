"""
Bear Market Optimization Implementation for Institutional Intraweek Enhanced Strategy

This file contains the specific code modifications needed to improve bear market performance
from -14.1% CAGR to target >-7% CAGR.

Key Changes:
1. Three-tier bear market regime detection (severe/moderate/mild)
2. Cash preservation strategy for severe bear markets
3. Counter-trend bounce strategy for moderate bear markets
4. Enhanced risk management and position sizing
5. Sector-specific filtering for bear markets

Implementation: Replace relevant methods in institutional_intraweek_enhanced.py
"""

from typing import Optional, Dict, List
from src.models import OHLCV, Recommendation
from src.utils.price_utils import ceil_to_step, floor_to_step, round_to_step
from src.utils.trading_hours import vnd_tick_size

class BearMarketOptimization:
    """Bear market optimization methods for institutional strategy."""

    def detect_enhanced_bear_regime(self, market_data: dict[str, list[OHLCV]]) -> str:
        """Enhanced bear market regime detection with severity levels.

        Replaces simple trending_bear with:
        - trending_bear_severe: >25% decline or >50% volatility
        - trending_bear_moderate: >15% decline or >35% volatility
        - trending_bear_mild: >5% decline with downtrend
        """
        # Get base regime using existing logic
        base_regime = self.detect_market_regime(market_data)

        if base_regime != "trending_bear":
            return base_regime

        # Analyze bear market severity
        market_candles = self._get_market_proxy_data(market_data)
        if not market_candles or len(market_candles) < 30:
            return "trending_bear_moderate"  # Default to moderate

        # Use 60-day lookback for severity analysis (matches 3-day signal frequency)
        lookback = min(60, len(market_candles))
        recent = market_candles[-lookback:]

        if len(recent) < 20:
            return "trending_bear_moderate"

        closes = [c.close for c in recent]

        # Calculate total decline from peak in period
        peak_close = max(closes)
        current_close = closes[-1]
        total_decline = (current_close - peak_close) / peak_close

        # Calculate volatility (annualized)
        returns = [(closes[i] / closes[i-1] - 1) for i in range(1, len(closes))]
        volatility = statistics.stdev(returns) * (252 ** 0.5) if len(returns) > 1 else 0.30

        # Classify bear market severity
        if total_decline < -0.25 or volatility > 0.50:  # Severe: >25% decline or >50% vol
            return "trending_bear_severe"
        elif total_decline < -0.15 or volatility > 0.35:  # Moderate: >15% decline or >35% vol
            return "trending_bear_moderate"
        else:
            return "trending_bear_mild"

    def _select_bear_market_strategy(self, regime: str, symbol: str) -> str:
        """Select strategy based on bear market severity and symbol characteristics.

        Strategy Selection:
        - trending_bear_severe: CASH_PRESERVATION (90% cash, defensive stocks only)
        - trending_bear_moderate: COUNTER_TREND_BOUNCE (oversold bounces)
        - trending_bear_mild: DEFENSIVE_MOMENTUM (selective momentum with tight stops)
        """
        if regime == "trending_bear_severe":
            # Only defensive stocks get cash preservation signals
            defensive_stocks = ['VNM', 'SAB', 'FPT', 'MSN', 'GAS', 'POW']
            return "CASH_PRESERVATION" if symbol in defensive_stocks else "NO_SIGNAL"

        elif regime == "trending_bear_moderate":
            # Avoid highly cyclical sectors for counter-trend bounces
            cyclical_stocks = ['HPG', 'HSG', 'NKG', 'VHM', 'VIC', 'VRE']
            return "NO_SIGNAL" if symbol in cyclical_stocks else "COUNTER_TREND_BOUNCE"

        elif regime == "trending_bear_mild":
            return "DEFENSIVE_MOMENTUM"

        return "mean_reversion"  # Fallback

    def _generate_cash_preservation_signal(
        self, symbol: str, weekly: list[OHLCV], daily: list[OHLCV],
        regime: str, held_symbols: set, conviction_score: float
    ) -> Optional[Recommendation]:
        """Generate ultra-conservative signals for severe bear market cash preservation.

        Entry Criteria:
        - Defensive stocks only (VNM, SAB, FPT, MSN, GAS, POW)
        - RSI < 25 (extreme oversold)
        - Volume surge >2.5x average (capitulation)
        - Ultra-tight stops (0.5x ATR)
        - Small position size (3% max)
        """
        # Only consider defensive stocks
        defensive_stocks = ['VNM', 'SAB', 'FPT', 'MSN', 'GAS', 'POW']
        if symbol not in defensive_stocks:
            return None

        if len(weekly) < max(self.bb_period, self.rsi_period):
            return None

        closes = [c.close for c in weekly]
        current_close = closes[-1]

        # Calculate technical indicators
        rsi = _rsi(closes, self.rsi_period)
        atr = _atr([c.high for c in weekly], [c.low for c in weekly], closes, self.atr_period)

        if rsi is None or atr is None:
            return None

        # Ultra-selective: Only extreme oversold
        if rsi > 25:  # Only extreme oversold conditions
            return None

        # Require significant volume surge (institutional capitulation signal)
        volume_surge_ratio = 1.0
        if len(daily) >= 20:
            recent_volume = sum(c.volume for c in daily[-3:]) / 3  # 3-day average
            historical_volume = sum(c.volume for c in daily[-20:-3]) / 17  # 17-day average
            if historical_volume > 0:
                volume_surge_ratio = recent_volume / historical_volume

        if volume_surge_ratio < 2.5:  # Require 2.5x volume surge
            return None

        # Conservative entry setup
        tick = vnd_tick_size(current_close)
        entry_price = round_to_step(current_close * 1.005, tick)  # Minimal 0.5% premium

        # Ultra-tight stop loss (capital preservation priority)
        stop_loss = floor_to_step(entry_price - 0.5 * atr, tick)  # 0.5x ATR (very tight)

        # Conservative take profit (quick exit on bounce)
        take_profit = ceil_to_step(entry_price + 1.5 * atr, tick)  # 1.5x ATR (3:1 R/R)

        rationale = [
            f"🛡️ SEVERE BEAR - CASH PRESERVATION | {regime.upper()}",
            f"📊 Defensive Stock: {symbol} RSI {rsi:.0f} (extreme oversold <25)",
            f"📈 Capitulation Signal: {volume_surge_ratio:.1f}x volume surge",
            f"🎯 Ultra-Conservative: 0.5x ATR stop, 1.5x ATR target",
            f"💰 Capital Preservation: 3% position max",
            f"🔥 Conviction: {conviction_score:.2f}/1.2"
        ]

        recommendation = Recommendation(
            symbol=symbol,
            asset_class="stock",
            action="BUY",
            buy_zone_low=entry_price,
            buy_zone_high=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_target_pct=0.03,  # Ultra-conservative 3% position
            rationale_bullets=rationale
        )

        recommendation.conviction_score = conviction_score
        return recommendation

    def _generate_counter_trend_bounce_signal(
        self, symbol: str, weekly: list[OHLCV], daily: list[OHLCV],
        regime: str, held_symbols: set, conviction_score: float
    ) -> Optional[Recommendation]:
        """Generate counter-trend bounce signals for moderate bear markets.

        Entry Criteria:
        - RSI < 30 (oversold)
        - Price near Bollinger Band lower
        - Volume exhaustion (<0.8x average)
        - Tight stops (1x ATR)
        - Moderate position size (8% max)
        """
        if len(weekly) < max(self.bb_period, self.rsi_period):
            return None

        closes = [c.close for c in weekly]
        current_close = closes[-1]

        # Calculate indicators for counter-trend setup
        rsi = _rsi(closes, self.rsi_period)
        bb_upper, bb_lower, bb_middle = self._bollinger_bands(closes, self.bb_period)
        atr = _atr([c.high for c in weekly], [c.low for c in weekly], closes, self.atr_period)

        if not all([rsi, bb_lower, atr]):
            return None

        # Counter-trend bounce setup requirements
        oversold_bounce = rsi <= 30  # Oversold level for bounce
        bb_bounce = current_close <= bb_lower * 1.02  # Within 2% of BB lower band

        if not (oversold_bounce and bb_bounce):
            return None

        # Volume exhaustion check (selling pressure diminishing)
        volume_exhaustion = False
        if len(daily) >= 10:
            recent_volume = daily[-1].volume
            avg_volume_5d = sum(c.volume for c in daily[-5:]) / 5
            volume_exhaustion = recent_volume < avg_volume_5d * 0.8  # Below 80% of 5-day avg

        if not volume_exhaustion:
            return None

        # Entry setup for counter-trend bounce
        tick = vnd_tick_size(current_close)
        entry_price = round_to_step(current_close * 1.01, tick)  # 1% premium for bounce

        # Tight stop (bear market can resume quickly)
        stop_loss = floor_to_step(entry_price - 1.0 * atr, tick)  # 1x ATR stop

        # Target BB middle or reasonable bounce level
        if bb_middle:
            # Target BB middle or 2.5x ATR, whichever is closer
            bb_target = bb_middle
            atr_target = entry_price + 2.5 * atr
            take_profit = ceil_to_step(min(bb_target, atr_target), tick)
        else:
            take_profit = ceil_to_step(entry_price + 2.0 * atr, tick)

        rationale = [
            f"⚡ MODERATE BEAR - COUNTER-TREND BOUNCE | {regime.upper()}",
            f"📊 Oversold Setup: RSI {rsi:.0f} (<30), Price {current_close:.0f} near BB Lower {bb_lower:.0f}",
            f"📉 Volume Exhaustion: {recent_volume:,.0f} < {avg_volume_5d:,.0f} (5d avg)",
            f"🎯 Bounce Target: BB Middle {bb_middle:.0f} (+{((take_profit/entry_price-1)*100):.1f}%)",
            f"⛔ Bear Market Protection: 1x ATR stop ({stop_loss:.0f})",
            f"🔥 Conviction: {conviction_score:.2f}/1.2"
        ]

        recommendation = Recommendation(
            symbol=symbol,
            asset_class="stock",
            action="BUY",
            buy_zone_low=entry_price,
            buy_zone_high=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_target_pct=0.08,  # Moderate 8% position
            rationale_bullets=rationale
        )

        recommendation.conviction_score = conviction_score
        return recommendation

    def _generate_defensive_momentum_signal(
        self, symbol: str, weekly: list[OHLCV], daily: list[OHLCV],
        regime: str, held_symbols: set, conviction_score: float
    ) -> Optional[Recommendation]:
        """Generate defensive momentum signals for mild bear markets.

        Entry Criteria:
        - RSI > 50 (above midline for momentum)
        - Price above short MA but selective
        - Volume confirmation
        - Tighter stops than normal bull market
        - Moderate position size (12% max)
        """
        if len(weekly) < max(self.ma_long, self.bb_period):
            return None

        closes = [c.close for c in weekly]
        current_close = closes[-1]

        # Calculate momentum indicators
        rsi = _rsi(closes, self.rsi_period)
        sma_short = _sma(closes, self.ma_short)
        sma_long = _sma(closes, self.ma_long)
        atr = _atr([c.high for c in weekly], [c.low for c in weekly], closes, self.atr_period)

        if not all([rsi, sma_short, sma_long, atr]):
            return None

        # Defensive momentum conditions (more selective than normal momentum)
        mild_momentum = rsi >= 55  # Above midline but not too high
        short_term_trend = current_close > sma_short  # Above short MA
        relative_strength = sma_short > sma_long * 0.98  # Short MA close to long MA (not diverging down)

        if not (mild_momentum and short_term_trend and relative_strength):
            return None

        # Volume confirmation (avoid low-volume rallies)
        volume_confirmed = False
        if len(daily) >= 10:
            recent_volume = sum(c.volume for c in daily[-3:]) / 3
            avg_volume = sum(c.volume for c in daily[-10:]) / 10
            volume_confirmed = recent_volume >= avg_volume * 1.1  # Above average volume

        if not volume_confirmed:
            return None

        # Entry setup
        tick = vnd_tick_size(current_close)
        entry_price = round_to_step(current_close * (1 + self.entry_buffer_pct), tick)

        # Tighter stop than normal momentum (bear market can resume)
        stop_multiplier = 1.2  # Tighter than normal momentum (1.6)
        stop_loss = floor_to_step(entry_price - stop_multiplier * atr, tick)

        # Conservative take profit
        target_multiplier = 2.5  # Lower than normal momentum (4.0)
        take_profit = ceil_to_step(entry_price + target_multiplier * atr, tick)

        rationale = [
            f"🛡️ MILD BEAR - DEFENSIVE MOMENTUM | {regime.upper()}",
            f"📊 Selective Momentum: RSI {rsi:.0f} (>55), Price {current_close:.0f} > MA{self.ma_short} {sma_short:.0f}",
            f"📈 Volume Confirmed: {recent_volume:,.0f} vs {avg_volume:,.0f} avg",
            f"🎯 Conservative Targets: {stop_multiplier}x ATR stop, {target_multiplier}x ATR target",
            f"⚖️ Risk Management: Tighter stops for bear market protection",
            f"🔥 Conviction: {conviction_score:.2f}/1.2"
        ]

        recommendation = Recommendation(
            symbol=symbol,
            asset_class="stock",
            action="BUY",
            buy_zone_low=entry_price,
            buy_zone_high=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_target_pct=0.12,  # Moderate 12% position
            rationale_bullets=rationale
        )

        recommendation.conviction_score = conviction_score
        return recommendation

    def _get_enhanced_kelly_parameters(self, regime: str) -> Dict[str, float]:
        """Get enhanced Kelly sizing parameters optimized for bear market performance.

        Replaces the ultra-aggressive parameters with realistic bear market expectations.
        """
        # Realistic win rates based on bear market backtesting
        win_rates = {
            "trending_bull": 0.82,           # Maintain strong bull performance
            "trending_bear_severe": 0.60,    # Conservative in severe bear (cash preservation)
            "trending_bear_moderate": 0.70,  # Better with counter-trend bounces
            "trending_bear_mild": 0.75,      # Reasonable with defensive momentum
            "sideways_volatile": 0.80,       # Maintain sideways performance
            "sideways_quiet": 0.78
        }

        # Adjusted win/loss ratios for bear market realities
        avg_win_loss_ratios = {
            "trending_bull": 4.0,            # Slightly lower from 4.5
            "trending_bear_severe": 3.0,     # 3:1 R/R with tight stops
            "trending_bear_moderate": 2.5,   # Counter-trend bounces have lower R/R
            "trending_bear_mild": 3.2,       # Defensive momentum targets
            "sideways_volatile": 3.5,        # Reduce from 3.8
            "sideways_quiet": 3.2            # Reduce from 3.5
        }

        # Conservative position size caps for bear markets
        max_sizes = {
            "trending_bull": 0.20,           # Reduce from 0.25 (more conservative)
            "trending_bear_severe": 0.05,    # Ultra-conservative 5% max (vs 15% original)
            "trending_bear_moderate": 0.10,  # Conservative 10% max
            "trending_bear_mild": 0.12,      # Moderate 12% max
            "sideways_volatile": 0.18,       # Reduce from 0.20
            "sideways_quiet": 0.15           # Reduce from 0.18
        }

        return {
            "win_rate": win_rates.get(regime, 0.70),
            "avg_win_loss": avg_win_loss_ratios.get(regime, 2.5),
            "max_size": max_sizes.get(regime, 0.10)
        }

    def generate_enhanced_signal(
        self, symbol: str, weekly: list[OHLCV], daily: list[OHLCV],
        regime: str, held_symbols: set, conviction_score: float
    ) -> Optional[Recommendation]:
        """Main signal generation method with bear market optimization.

        This replaces the existing momentum/mean reversion logic with bear market-aware strategies.
        """
        # Determine strategy based on enhanced regime
        strategy_type = self._select_bear_market_strategy(regime, symbol)

        if strategy_type == "NO_SIGNAL":
            return None
        elif strategy_type == "CASH_PRESERVATION":
            return self._generate_cash_preservation_signal(
                symbol, weekly, daily, regime, held_symbols, conviction_score
            )
        elif strategy_type == "COUNTER_TREND_BOUNCE":
            return self._generate_counter_trend_bounce_signal(
                symbol, weekly, daily, regime, held_symbols, conviction_score
            )
        elif strategy_type == "DEFENSIVE_MOMENTUM":
            return self._generate_defensive_momentum_signal(
                symbol, weekly, daily, regime, held_symbols, conviction_score
            )
        else:
            # Fallback to existing mean reversion logic for non-bear regimes
            return self._generate_enhanced_mean_reversion_signal(
                symbol, weekly, daily, regime, held_symbols, conviction_score
            )


# Required helper functions (add to institutional_intraweek_enhanced.py)

def _rsi(closes: list[float], period: int) -> float | None:
    """Calculate RSI with enhanced smoothing."""
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


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int) -> float | None:
    """Calculate Average True Range."""
    if len(highs) < period + 1:
        return None

    trs = []
    for i in range(-period, 0):
        tr1 = highs[i] - lows[i]
        tr2 = abs(highs[i] - closes[i - 1]) if i > 0 else 0
        tr3 = abs(lows[i] - closes[i - 1]) if i > 0 else 0
        trs.append(max(tr1, tr2, tr3))

    return sum(trs) / len(trs) if trs else None