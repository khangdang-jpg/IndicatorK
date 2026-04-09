"""Dual-Stream Signal Combination Strategy.

This strategy combines both the weekly trend momentum strategy and the enhanced
intraweek strategy to capture complementary signal streams while preserving all
existing system features:

Architecture:
- Weekly Engine: Large trends, bigger positions, longer holds (26.14% bull CAGR)
- Intraweek Engine: Tactical entries, smaller positions, frequent signals (19.6% bull CAGR)
- Combined Output: 60% weekly + 40% intraweek weighted signals

Critical System Inheritance:
✅ Risk-based position sizing (size based on stop-loss distance)
✅ AI news integration (Groq analysis + news-based buy potential scoring)
✅ Position preservation logic (existing stop-loss maintenance for held positions)
✅ Unified asset tracking (single portfolio state management)
✅ All existing risk controls and guardrails

Expected Performance:
- Bull Markets: ~23% CAGR (60% × 26.14% + 40% × 19.6%)
- Overall Average: ~10-12% CAGR with enhanced opportunity capture
- Signal Frequency: 16-20 trades/period (vs 10-12 weekly, 6-8 intraweek)
- Risk Control: Maintained through inherited position sizing and stop-loss logic
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from src.models import PortfolioState, Recommendation, WeeklyPlan
from src.strategies.base import Strategy
from src.strategies.trend_momentum_atr_regime_adaptive import TrendMomentumATRRegimeAdaptive
from src.strategies.institutional_intraweek_enhanced import InstitutionalIntraweekEnhanced

logger = logging.getLogger(__name__)


class DualStreamCombined(Strategy):
    """Dual-stream strategy combining weekly and intraweek signals with full inheritance."""

    def __init__(self, params: dict | None = None):
        """Initialize dual-stream strategy with both sub-strategies."""
        params = params or {}

        # Initialize both sub-strategies with their existing parameters
        self.weekly_strategy = TrendMomentumATRRegimeAdaptive(params.get("weekly", {}))
        self.intraweek_strategy = InstitutionalIntraweekEnhanced(params.get("intraweek", {}))

        # Dual-stream specific parameters
        self.weekly_weight = params.get("weekly_weight", 0.60)
        self.intraweek_weight = params.get("intraweek_weight", 0.40)
        self.max_combined_position = params.get("max_combined_position", 0.25)

    @property
    def id(self) -> str:
        return "dual_stream_combined"

    @property
    def version(self) -> str:
        return "1.0.0"

    def generate_weekly_plan(
        self,
        market_data: dict,
        portfolio_state: PortfolioState,
        config: dict,
    ) -> WeeklyPlan:
        """Generate combined weekly plan from both strategies with full inheritance."""
        logger.info("Generating dual-stream combined plan (60% weekly + 40% intraweek)")

        # STEP 1: Generate signals from both strategies (inherit all existing logic)
        logger.info("Generating weekly strategy signals...")
        weekly_plan = self.weekly_strategy.generate_weekly_plan(market_data, portfolio_state, config)

        logger.info("Generating intraweek strategy signals...")
        intraweek_plan = self.intraweek_strategy.generate_weekly_plan(market_data, portfolio_state, config)

        # STEP 2: Preserve existing position logic (inherit from weekly strategy)
        held_symbols = set(portfolio_state.positions.keys())
        logger.info(f"Found {len(held_symbols)} held positions: {held_symbols}")

        # STEP 3: Merge signals with risk-based position sizing
        logger.info("Merging signals with unified asset tracking...")
        combined_recommendations = self._merge_signals_with_unified_tracking(
            weekly_plan.recommendations,
            intraweek_plan.recommendations,
            held_symbols,
            config
        )

        # STEP 4: Create unified plan (inherit existing structure)
        unified_plan = WeeklyPlan(
            generated_at=datetime.utcnow().isoformat(),
            strategy_id=self.id,
            strategy_version=self.version,
            allocation_targets=weekly_plan.allocation_targets,  # Inherit existing allocation
            recommendations=combined_recommendations,
            notes=self._create_dual_stream_notes(weekly_plan, intraweek_plan),
            market_regime=f"{weekly_plan.market_regime or 'unknown'}+{intraweek_plan.market_regime or 'unknown'}"
        )

        logger.info(f"Generated {len(combined_recommendations)} combined recommendations")

        # STEP 5: AI analysis and news integration will be applied automatically
        # in run_weekly.py after strategy execution (no changes needed)

        return unified_plan

    def _load_previous_weekly_plan(self) -> WeeklyPlan | None:
        """Load the previous weekly plan to preserve original stop losses for held positions.

        INHERITED: This method is copied from the weekly strategy to ensure
        position preservation logic works correctly.
        """
        plan_path = Path("data/weekly_plan.json")
        if not plan_path.exists():
            return None

        try:
            with open(plan_path) as f:
                data = json.load(f)

            # Convert dict back to WeeklyPlan object
            recommendations = []
            for rec_data in data.get("recommendations", []):
                rec = Recommendation(
                    symbol=rec_data["symbol"],
                    asset_class=rec_data["asset_class"],
                    action=rec_data["action"],
                    buy_zone_low=rec_data["buy_zone_low"],
                    buy_zone_high=rec_data["buy_zone_high"],
                    stop_loss=rec_data["stop_loss"],
                    take_profit=rec_data["take_profit"],
                    position_target_pct=rec_data["position_target_pct"],
                    rationale_bullets=rec_data.get("rationale_bullets", []),
                    entry_type=rec_data.get("entry_type", "pullback"),
                    breakout_level=rec_data.get("breakout_level", 0.0),
                    entry_price=rec_data.get("entry_price", 0.0),
                )
                recommendations.append(rec)

            return WeeklyPlan(
                generated_at=data["generated_at"],
                strategy_id=data["strategy_id"],
                strategy_version=data["strategy_version"],
                allocation_targets=data["allocation_targets"],
                recommendations=recommendations,
                notes=data.get("notes", []),
                ai_analysis=data.get("ai_analysis"),
                news_analysis=data.get("news_analysis"),
                market_regime=data.get("market_regime")
            )

        except Exception as e:
            logger.warning(f"Failed to load previous weekly plan: {e}")
            return None

    def _merge_signals_with_unified_tracking(
        self,
        weekly_recs: list[Recommendation],
        intraweek_recs: list[Recommendation],
        held_symbols: set[str],
        config: dict
    ) -> list[Recommendation]:
        """Merge signals with unified asset tracking and position preservation.

        INHERITED: Position preservation logic from weekly strategy with
        unified asset tracking across both strategies.
        """
        # INHERIT: Position preservation logic from weekly strategy
        previous_plan = self._load_previous_weekly_plan()
        previous_recommendations = {}
        if previous_plan:
            previous_recommendations = {rec.symbol: rec for rec in previous_plan.recommendations}
            logger.info(f"Loaded {len(previous_recommendations)} previous recommendations for preservation")

        combined_recommendations = []

        # Collect all symbols from both strategies
        weekly_symbols = {rec.symbol: rec for rec in weekly_recs}
        intraweek_symbols = {rec.symbol: rec for rec in intraweek_recs}
        all_symbols = set(weekly_symbols.keys()) | set(intraweek_symbols.keys())

        logger.info(f"Processing {len(all_symbols)} unique symbols across both strategies")
        logger.info(f"Weekly signals: {len(weekly_symbols)}, Intraweek signals: {len(intraweek_symbols)}")

        for symbol in all_symbols:
            weekly_rec = weekly_symbols.get(symbol)
            intraweek_rec = intraweek_symbols.get(symbol)

            # INHERIT: Handle existing positions (preserve original stop losses)
            if symbol in held_symbols:
                merged_rec = self._handle_existing_position(
                    symbol, weekly_rec, intraweek_rec, previous_recommendations.get(symbol)
                )
                if merged_rec:
                    logger.info(f"Preserved position for {symbol}: {merged_rec.action}")
            else:
                # New position - combine signals
                merged_rec = self._combine_new_position_signals(weekly_rec, intraweek_rec, config)
                if merged_rec:
                    logger.info(f"Combined new signal for {symbol}: {merged_rec.action} {merged_rec.position_target_pct:.1%}")

            if merged_rec:
                combined_recommendations.append(merged_rec)

        return combined_recommendations

    def _handle_existing_position(
        self,
        symbol: str,
        weekly_rec: Recommendation | None,
        intraweek_rec: Recommendation | None,
        prev_rec: Recommendation | None
    ) -> Recommendation | None:
        """Handle existing positions by preserving original stop losses.

        INHERITED: Stop-loss preservation logic from weekly strategy.
        """
        if prev_rec and prev_rec.stop_loss > 0:
            preserved_stop = prev_rec.stop_loss

            # Use the more conservative action (SELL > REDUCE > HOLD > BUY)
            action_priority = {"SELL": 4, "REDUCE": 3, "HOLD": 2, "BUY": 1}

            actions = []
            if weekly_rec:
                actions.append((weekly_rec.action, weekly_rec, "WEEKLY"))
            if intraweek_rec:
                actions.append((intraweek_rec.action, intraweek_rec, "INTRAWEEK"))

            if actions:
                # Take most conservative action
                primary_action, primary_rec, source = max(actions, key=lambda x: action_priority.get(x[0], 0))

                # Create new recommendation with preserved stop loss
                preserved_rec = Recommendation(
                    symbol=primary_rec.symbol,
                    asset_class=primary_rec.asset_class,
                    action=primary_rec.action,
                    buy_zone_low=primary_rec.buy_zone_low,
                    buy_zone_high=primary_rec.buy_zone_high,
                    stop_loss=preserved_stop,  # Preserve original stop
                    take_profit=primary_rec.take_profit,
                    position_target_pct=primary_rec.position_target_pct,
                    rationale_bullets=primary_rec.rationale_bullets + [
                        f"🔒 Preserved original SL: {preserved_stop:.0f}",
                        f"📊 Primary signal: {source}"
                    ],
                    entry_type=primary_rec.entry_type,
                    breakout_level=primary_rec.breakout_level,
                    entry_price=primary_rec.entry_price,
                )
                return preserved_rec

        return None

    def _combine_new_position_signals(
        self,
        weekly_rec: Recommendation | None,
        intraweek_rec: Recommendation | None,
        config: dict
    ) -> Recommendation | None:
        """Combine signals for new positions with risk-based position sizing.

        INHERITED: Risk-based position sizing logic while combining signals.
        """
        if weekly_rec and intraweek_rec and weekly_rec.action == "BUY" and intraweek_rec.action == "BUY":
            # Both strategies want to buy - create combined position

            # INHERIT: Risk-based sizing for both components
            weekly_position = self._calculate_risk_based_position_size(weekly_rec, config)
            intraweek_position = self._calculate_risk_based_position_size(intraweek_rec, config)

            # Weight positions and combine
            combined_position = min(
                weekly_position * self.weekly_weight + intraweek_position * self.intraweek_weight,
                self.max_combined_position
            )

            # Create merged recommendation
            return Recommendation(
                symbol=weekly_rec.symbol,
                asset_class=weekly_rec.asset_class,
                action="BUY",
                buy_zone_low=min(weekly_rec.buy_zone_low, intraweek_rec.buy_zone_low),
                buy_zone_high=max(weekly_rec.buy_zone_high, intraweek_rec.buy_zone_high),
                stop_loss=max(weekly_rec.stop_loss, intraweek_rec.stop_loss),  # Tighter stop
                take_profit=max(weekly_rec.take_profit, intraweek_rec.take_profit),  # Higher target
                position_target_pct=combined_position,
                entry_type=weekly_rec.entry_type,  # Weekly takes precedence
                breakout_level=weekly_rec.breakout_level,
                entry_price=weekly_rec.entry_price,
                rationale_bullets=(
                    [f"📈 WEEKLY: {r}" for r in weekly_rec.rationale_bullets] +
                    [f"⚡ INTRAWEEK: {r}" for r in intraweek_rec.rationale_bullets] +
                    [f"🔄 DUAL-STREAM: Combined {combined_position:.1%} position ({weekly_position*self.weekly_weight:.1%}+{intraweek_position*self.intraweek_weight:.1%})"]
                )
            )

        elif weekly_rec and weekly_rec.action == "BUY":
            # Weekly signal only - apply weekly weighting
            weekly_position = self._calculate_risk_based_position_size(weekly_rec, config) * self.weekly_weight
            weekly_rec.position_target_pct = weekly_position
            weekly_rec.rationale_bullets = [f"📈 WEEKLY: {r}" for r in weekly_rec.rationale_bullets]
            weekly_rec.rationale_bullets.append(f"📈 WEEKLY ONLY: {weekly_position:.1%} position")
            return weekly_rec

        elif intraweek_rec and intraweek_rec.action == "BUY":
            # Intraweek signal only - apply intraweek weighting
            intraweek_position = self._calculate_risk_based_position_size(intraweek_rec, config) * self.intraweek_weight
            intraweek_rec.position_target_pct = intraweek_position
            intraweek_rec.rationale_bullets = [f"⚡ TACTICAL: {r}" for r in intraweek_rec.rationale_bullets]
            intraweek_rec.rationale_bullets.append(f"⚡ INTRAWEEK ONLY: {intraweek_position:.1%} position")
            return intraweek_rec

        # Handle SELL, REDUCE, HOLD actions (weekly takes precedence for exits)
        elif weekly_rec and weekly_rec.action in ["SELL", "REDUCE", "HOLD"]:
            weekly_rec.rationale_bullets = [f"📈 WEEKLY: {r}" for r in weekly_rec.rationale_bullets]
            weekly_rec.rationale_bullets.append("📈 WEEKLY EXIT SIGNAL")
            return weekly_rec
        elif intraweek_rec and intraweek_rec.action in ["SELL", "REDUCE", "HOLD"]:
            intraweek_rec.rationale_bullets = [f"⚡ TACTICAL: {r}" for r in intraweek_rec.rationale_bullets]
            intraweek_rec.rationale_bullets.append("⚡ INTRAWEEK EXIT SIGNAL")
            return intraweek_rec

        return None

    def _calculate_risk_based_position_size(self, recommendation: Recommendation, config: dict) -> float:
        """Calculate risk-based position size using stop-loss distance.

        INHERITED: Existing risk-based position sizing formula from weekly strategy.
        """
        risk_per_trade_pct = config.get("position", {}).get("risk_per_trade_pct", 0.02)

        # Calculate stop distance as percentage
        if recommendation.stop_loss > 0 and recommendation.entry_price > 0:
            stop_distance_pct = abs(recommendation.entry_price - recommendation.stop_loss) / recommendation.entry_price

            # Risk-based position size = risk_per_trade / stop_distance
            position_pct = risk_per_trade_pct / stop_distance_pct if stop_distance_pct > 0 else 0.0
        else:
            # Fallback to fixed percentage
            position_pct = config.get("position", {}).get("base_position_pct", 0.10)

        # Apply regime multipliers (use generic multiplier for combined strategy)
        regime_multiplier = 1.0  # Balanced approach for dual-stream
        final_position = position_pct * regime_multiplier

        # Cap position size
        max_position = config.get("position", {}).get("max_position_pct", 0.25)
        return min(final_position, max_position)

    def _create_dual_stream_notes(self, weekly_plan: WeeklyPlan, intraweek_plan: WeeklyPlan) -> list[str]:
        """Create combined notes from both strategies."""
        notes = [
            "🔄 DUAL-STREAM COMBINED STRATEGY",
            f"📈 Weekly Strategy: {weekly_plan.strategy_id} v{weekly_plan.strategy_version}",
            f"⚡ Intraweek Strategy: {intraweek_plan.strategy_id} v{intraweek_plan.strategy_version}",
            f"⚖️ Signal Weights: {self.weekly_weight:.0%} Weekly + {self.intraweek_weight:.0%} Intraweek",
            f"🎯 Max Combined Position: {self.max_combined_position:.0%}",
            "",
            "📈 WEEKLY PLAN NOTES:"
        ]

        for note in weekly_plan.notes:
            notes.append(f"  • {note}")

        notes.append("")
        notes.append("⚡ INTRAWEEK PLAN NOTES:")

        for note in intraweek_plan.notes:
            notes.append(f"  • {note}")

        notes.extend([
            "",
            "✅ SYSTEM INHERITANCE:",
            "  • Risk-based position sizing (stop-loss distance formula)",
            "  • AI news integration (automatic post-strategy)",
            "  • Position preservation logic (original stop-loss maintenance)",
            "  • Unified asset tracking (single portfolio state)",
            "  • All existing risk controls and guardrails"
        ])

        return notes