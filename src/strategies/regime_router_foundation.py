"""Regime router that delegates to specialized engines per market type."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from statistics import pstdev

from src.models import OHLCV, PortfolioState, Recommendation, WeeklyPlan
from src.strategies.base import Strategy
from src.strategies.institutional_intraweek_enhanced import InstitutionalIntraweekEnhanced


class _ForcedBullInstitutional(InstitutionalIntraweekEnhanced):
    """Institutional engine pinned to bull-mode momentum logic."""

    def detect_market_regime(self, market_data: dict[str, list[OHLCV]]) -> str:
        return "trending_bull"


class _ForcedSidewayInstitutional(InstitutionalIntraweekEnhanced):
    """Institutional engine pinned to sideway-mode mean-reversion logic."""

    def detect_market_regime(self, market_data: dict[str, list[OHLCV]]) -> str:
        return "sideways_quiet"


@dataclass
class _RegimeSnapshot:
    proxy_ret_20: float
    proxy_ret_60: float
    breadth_20: float
    breadth_50: float
    avg_ret_20: float
    avg_daily_vol_20: float


class RegimeRouterFoundation(Strategy):
    """Use distinct strategy foundations for bear, sideway, and bull markets."""

    MARKET_LEADERS = ["VCB", "MBB", "TCB", "HPG", "FPT", "VNM", "VHM", "SSI", "CTG", "GAS"]
    SYMBOL_TO_SECTOR = {
        symbol: sector
        for sector, symbols in InstitutionalIntraweekEnhanced.SECTOR_MAP.items()
        for symbol in symbols
    }

    def __init__(self, params: dict | None = None):
        params = params or {}

        self.bear_proxy_ret_60 = float(params.get("bear_proxy_ret_60", -0.10))
        self.bear_breadth_20 = float(params.get("bear_breadth_20", 0.30))
        self.bear_breadth_50 = float(params.get("bear_breadth_50", 0.30))
        self.bear_proxy_ret_20_cap = float(params.get("bear_proxy_ret_20_cap", 0.03))
        self.sideway_proxy_ret_20_abs = float(params.get("sideway_proxy_ret_20_abs", 0.03))
        self.sideway_proxy_ret_60_abs = float(params.get("sideway_proxy_ret_60_abs", 0.06))
        self.sideway_breadth_20_min = float(params.get("sideway_breadth_20_min", 0.35))
        self.sideway_breadth_20_max = float(params.get("sideway_breadth_20_max", 0.75))
        self.bull_hysteresis_proxy_ret_20 = float(params.get("bull_hysteresis_proxy_ret_20", -0.03))
        self.bear_hysteresis_proxy_ret_60 = float(params.get("bear_hysteresis_proxy_ret_60", -0.03))
        self.bear_hysteresis_breadth_50 = float(params.get("bear_hysteresis_breadth_50", 0.45))
        self.bear_max_new_positions = int(params.get("bear_max_new_positions", 0))
        self.sideway_max_new_positions = int(params.get("sideway_max_new_positions", 6))
        self.bull_max_new_positions = int(params.get("bull_max_new_positions", 4))
        self.bull_transition_max_new_positions = int(params.get("bull_transition_max_new_positions", 5))
        self.strong_bull_proxy_ret_20 = float(params.get("strong_bull_proxy_ret_20", 0.05))
        self.strong_bull_breadth_20 = float(params.get("strong_bull_breadth_20", 0.70))
        self.strong_bull_breadth_50 = float(params.get("strong_bull_breadth_50", 0.65))
        self.bull_caution_proxy_ret_20_max = float(params.get("bull_caution_proxy_ret_20_max", 0.015))
        self.bull_caution_breadth_20_max = float(params.get("bull_caution_breadth_20_max", 0.25))
        self.bull_caution_breadth_50_max = float(params.get("bull_caution_breadth_50_max", 0.75))
        self.bull_caution_max_new_positions = int(params.get("bull_caution_max_new_positions", 1))
        self.bull_caution_ret_lookback = int(params.get("bull_caution_ret_lookback", 5))
        self.bull_caution_ma_short = int(params.get("bull_caution_ma_short", 10))
        self.bull_caution_ma_long = int(params.get("bull_caution_ma_long", 20))
        self.bull_allow_add_ons = bool(params.get("bull_allow_add_ons", False))
        self.bull_max_open_trades_per_symbol = int(params.get("bull_max_open_trades_per_symbol", 1))
        self.bull_max_symbols_per_sector = int(params.get("bull_max_symbols_per_sector", 2))
        self.bull_add_on_size_scale = float(params.get("bull_add_on_size_scale", 0.20))
        self.bull_add_on_min_conviction = float(params.get("bull_add_on_min_conviction", 0.85))
        self.bull_low_vol_threshold = float(params.get("bull_low_vol_threshold", 0.020))
        self.bull_high_vol_threshold = float(params.get("bull_high_vol_threshold", 0.035))
        self.bull_low_vol_stock_target = float(params.get("bull_low_vol_stock_target", 1.00))
        self.bull_high_vol_stock_target = float(params.get("bull_high_vol_stock_target", 0.88))
        self.bull_max_deployment_scale = float(params.get("bull_max_deployment_scale", 2.40))
        self.bull_position_target_cap = float(params.get("bull_position_target_cap", 0.45))
        self.sideway_low_vol_threshold = float(params.get("sideway_low_vol_threshold", 0.012))
        self.sideway_high_vol_threshold = float(params.get("sideway_high_vol_threshold", 0.024))
        self.sideway_low_vol_stock_target = float(params.get("sideway_low_vol_stock_target", 0.84))
        self.sideway_high_vol_stock_target = float(params.get("sideway_high_vol_stock_target", 0.66))
        self.sideway_max_deployment_scale = float(params.get("sideway_max_deployment_scale", 1.30))
        self.sideway_position_target_cap = float(params.get("sideway_position_target_cap", 0.18))
        self.previous_regime = "sideway"
        self._last_snapshot = _RegimeSnapshot(0.0, 0.0, 0.5, 0.5, 0.0, 0.015)

        bull_params = {
            "momentum_rsi_min": params.get("bull_momentum_rsi_min", 46),
            "momentum_atr_stop": params.get("bull_momentum_atr_stop", 1.6),
            "momentum_stop_floor_pct": params.get("bull_momentum_stop_floor_pct", 0.92),
            "volume_surge_threshold": params.get("bull_volume_surge_threshold", 1.1),
            "kelly_fraction": params.get("bull_kelly_fraction", 0.45),
            "momentum_atr_target": params.get("bull_momentum_atr_target", 6.0),
            "bull_breakout_min_conviction": params.get("bull_breakout_min_conviction", 0.92),
            "bull_breakout_volume_relax": params.get("bull_breakout_volume_relax", 0.78),
        }
        sideway_params = {
            "mean_revert_rsi_oversold": params.get("sideway_rsi_oversold", 30),
            "mean_revert_atr_target": params.get("sideway_atr_target", 3.0),
            "bb_std_mult": params.get("sideway_bb_std_mult", 1.6),
            "kelly_fraction": params.get("sideway_kelly_fraction", 0.4),
        }

        self.bull_strategy = _ForcedBullInstitutional(bull_params)
        self.sideway_strategy = _ForcedSidewayInstitutional(sideway_params)

    @property
    def id(self) -> str:
        return "regime_router_foundation"

    @property
    def version(self) -> str:
        return "1.0.0"

    def _market_symbol_data(self, market_data: dict[str, list[OHLCV]]) -> dict[str, list[OHLCV]]:
        return {
            symbol: candles
            for symbol, candles in market_data.items()
            if symbol not in {"VNINDEX", "VNI", "^VNINDEX"} and len(candles) >= 60
        }

    def _build_snapshot(self, market_data: dict[str, list[OHLCV]]) -> _RegimeSnapshot:
        symbol_data = self._market_symbol_data(market_data)
        leaders = [symbol for symbol in self.MARKET_LEADERS if symbol in symbol_data]
        sample = leaders or list(symbol_data.keys())

        proxy_rets_20: list[float] = []
        proxy_rets_60: list[float] = []
        avg_rets_20: list[float] = []
        vols_20: list[float] = []
        breadth_20_count = 0
        breadth_50_count = 0
        total = 0

        for symbol in sample:
            candles = symbol_data[symbol]
            closes = [c.close for c in candles]
            current = closes[-1]
            ma20 = sum(closes[-20:]) / 20
            ma50 = sum(closes[-50:]) / 50
            ret_20 = (current - closes[-20]) / closes[-20] if closes[-20] else 0.0
            ret_60 = (current - closes[-60]) / closes[-60] if closes[-60] else 0.0
            daily_returns = [
                (closes[idx] - closes[idx - 1]) / closes[idx - 1]
                for idx in range(len(closes) - 19, len(closes))
                if closes[idx - 1]
            ]

            proxy_rets_20.append(ret_20)
            proxy_rets_60.append(ret_60)
            avg_rets_20.append(ret_20)
            breadth_20_count += 1 if current > ma20 else 0
            breadth_50_count += 1 if current > ma50 else 0
            avg_daily_vol_20 = pstdev(daily_returns) if len(daily_returns) >= 2 else 0.0
            vols_20.append(avg_daily_vol_20)
            total += 1

        if total == 0:
            return _RegimeSnapshot(0.0, 0.0, 0.5, 0.5, 0.0, 0.015)

        return _RegimeSnapshot(
            proxy_ret_20=sum(proxy_rets_20) / len(proxy_rets_20),
            proxy_ret_60=sum(proxy_rets_60) / len(proxy_rets_60),
            breadth_20=breadth_20_count / total,
            breadth_50=breadth_50_count / total,
            avg_ret_20=sum(avg_rets_20) / len(avg_rets_20),
            avg_daily_vol_20=sum(vols_20) / len(vols_20),
        )

    def _interpolate_target(
        self,
        vol: float,
        low_threshold: float,
        high_threshold: float,
        low_target: float,
        high_target: float,
    ) -> float:
        if not isfinite(vol):
            return low_target
        if vol <= low_threshold:
            return low_target
        if vol >= high_threshold:
            return high_target
        span = high_threshold - low_threshold
        if span <= 0:
            return low_target
        ratio = (vol - low_threshold) / span
        return low_target + (high_target - low_target) * ratio

    def _apply_deployment_policy(
        self,
        plan: WeeklyPlan,
        portfolio_state: PortfolioState,
        regime: str,
    ) -> WeeklyPlan:
        if regime not in {"bull", "sideway"}:
            return plan

        held_symbols = set(portfolio_state.positions.keys())
        buy_recommendations = [
            r
            for r in plan.recommendations
            if r.action == "BUY"
            and r.position_target_pct > 0
            and r.symbol not in held_symbols
        ]
        if not buy_recommendations:
            return plan

        if regime == "bull":
            desired_stock_target = self._interpolate_target(
                self._last_snapshot.avg_daily_vol_20,
                self.bull_low_vol_threshold,
                self.bull_high_vol_threshold,
                self.bull_low_vol_stock_target,
                self.bull_high_vol_stock_target,
            )
            max_scale = self.bull_max_deployment_scale
            position_cap = self.bull_position_target_cap
        else:
            desired_stock_target = self._interpolate_target(
                self._last_snapshot.avg_daily_vol_20,
                self.sideway_low_vol_threshold,
                self.sideway_high_vol_threshold,
                self.sideway_low_vol_stock_target,
                self.sideway_high_vol_stock_target,
            )
            max_scale = self.sideway_max_deployment_scale
            position_cap = self.sideway_position_target_cap

        current_stock_pct = float(portfolio_state.allocation.get("stock_pct", 0.0))
        base_planned_pct = sum(rec.position_target_pct for rec in buy_recommendations)
        remaining_budget = max(desired_stock_target - current_stock_pct, 0.0)
        if base_planned_pct <= 0 or remaining_budget <= base_planned_pct:
            plan.allocation_targets["stock"] = desired_stock_target
            plan.allocation_targets["bond_fund"] = max(0.0, 1.0 - desired_stock_target)
            return plan

        scale = min(max_scale, remaining_budget / base_planned_pct)
        if scale <= 1.02:
            plan.allocation_targets["stock"] = desired_stock_target
            plan.allocation_targets["bond_fund"] = max(0.0, 1.0 - desired_stock_target)
            return plan

        for rec in buy_recommendations:
            original_pct = rec.position_target_pct
            rec.position_target_pct = min(rec.position_target_pct * scale, position_cap)
            if rec.position_target_pct > original_pct:
                rec.rationale_bullets.append(
                    f"Deployment scaled in {regime} regime: {original_pct:.1%} -> {rec.position_target_pct:.1%} as unused cash remained high."
                )

        plan.allocation_targets["stock"] = desired_stock_target
        plan.allocation_targets["bond_fund"] = max(0.0, 1.0 - desired_stock_target)
        plan.notes.append(
            f"Vol-targeted deployment: stock target {desired_stock_target:.0%} with avg daily vol {self._last_snapshot.avg_daily_vol_20:.2%}."
        )
        return plan

    def detect_regime(self, market_data: dict[str, list[OHLCV]]) -> str:
        snap = self._build_snapshot(market_data)
        self._last_snapshot = snap

        bear = (
            snap.proxy_ret_60 <= self.bear_proxy_ret_60
            or (
                snap.breadth_20 <= self.bear_breadth_20
                and snap.breadth_50 <= self.bear_breadth_50
                and snap.proxy_ret_20 <= self.bear_proxy_ret_20_cap
            )
        )
        sideway = (
            abs(snap.proxy_ret_20) <= self.sideway_proxy_ret_20_abs
            and abs(snap.proxy_ret_60) <= self.sideway_proxy_ret_60_abs
            and self.sideway_breadth_20_min <= snap.breadth_20 <= self.sideway_breadth_20_max
        )

        if self.previous_regime == "bull" and not bear and snap.proxy_ret_20 > self.bull_hysteresis_proxy_ret_20:
            sideway = False

        if (
            self.previous_regime == "bear"
            and snap.proxy_ret_60 < self.bear_hysteresis_proxy_ret_60
            and snap.breadth_50 < self.bear_hysteresis_breadth_50
        ):
            bear = True

        if bear:
            regime = "bear"
        elif sideway:
            regime = "sideway"
        else:
            regime = "bull"

        self.previous_regime = regime
        return regime

    def _is_strong_bull(self, snap: _RegimeSnapshot) -> bool:
        return (
            snap.proxy_ret_20 >= self.strong_bull_proxy_ret_20
            and snap.breadth_20 >= self.strong_bull_breadth_20
            and snap.breadth_50 >= self.strong_bull_breadth_50
        )

    def _is_bull_caution(self, snap: _RegimeSnapshot) -> bool:
        return (
            snap.proxy_ret_20 <= self.bull_caution_proxy_ret_20_max
            and snap.breadth_20 <= self.bull_caution_breadth_20_max
            and snap.breadth_50 <= self.bull_caution_breadth_50_max
        )

    def _cash_plan(self, portfolio_state: PortfolioState) -> WeeklyPlan:
        recommendations: list[Recommendation] = []
        for symbol in portfolio_state.positions.keys():
            recommendations.append(
                Recommendation(
                    symbol=symbol,
                    asset_class="stock",
                    action="SELL",
                    buy_zone_low=0.0,
                    buy_zone_high=0.0,
                    stop_loss=0.0,
                    take_profit=0.0,
                    position_target_pct=0.0,
                    rationale_bullets=["Bear regime: preserve capital and move to cash."],
                )
            )

        return WeeklyPlan(
            generated_at=datetime.utcnow().isoformat(),
            strategy_id=self.id,
            strategy_version=self.version,
            allocation_targets={"stock": 0.0, "bond_fund": 1.0},
            recommendations=recommendations,
            max_new_positions=self.bear_max_new_positions,
            allow_symbol_add_ons=False,
            max_open_trades_per_symbol=1,
            force_defensive_exits=True,
            market_regime="bear",
            notes=["Regime router selected BEAR mode: capital preservation first."],
        )

    def _apply_bull_add_on_policy(
        self,
        plan: WeeklyPlan,
        portfolio_state: PortfolioState,
    ) -> WeeklyPlan:
        held_symbols = set(portfolio_state.positions.keys())
        filtered_recommendations: list[Recommendation] = []

        for recommendation in plan.recommendations:
            if recommendation.action != "BUY" or recommendation.symbol not in held_symbols:
                filtered_recommendations.append(recommendation)
                continue

            if not self.bull_allow_add_ons:
                continue

            conviction = float(getattr(recommendation, "conviction_score", 0.0))
            is_momentum = any("MOMENTUM" in bullet for bullet in recommendation.rationale_bullets)
            if not is_momentum or conviction < self.bull_add_on_min_conviction:
                continue

            recommendation.position_target_pct *= self.bull_add_on_size_scale
            recommendation.rationale_bullets.append(
                f"Bull add-on enabled: scale into existing winner at {self.bull_add_on_size_scale:.0%} of base size."
            )
            filtered_recommendations.append(recommendation)

        plan.recommendations = filtered_recommendations
        plan.allow_symbol_add_ons = self.bull_allow_add_ons
        plan.max_open_trades_per_symbol = self.bull_max_open_trades_per_symbol
        return plan

    def _restrict_transition_bull_entries(self, plan: WeeklyPlan, strong_bull: bool) -> WeeklyPlan:
        if strong_bull:
            return plan

        for recommendation in plan.recommendations:
            if recommendation.action != "BUY" or recommendation.entry_type != "breakout":
                continue
            recommendation.entry_type = "pullback"
            recommendation.breakout_level = 0.0
            recommendation.rationale_bullets.append(
                "Transition bull guardrail: breakout trigger downgraded to pullback entry."
            )
        return plan

    def _apply_sector_diversification(
        self,
        plan: WeeklyPlan,
        portfolio_state: PortfolioState,
        regime: str,
    ) -> WeeklyPlan:
        if regime != "bull" or self.bull_max_symbols_per_sector <= 0:
            return plan

        sector_counts: dict[str, int] = {}
        for symbol in portfolio_state.positions.keys():
            sector = self.SYMBOL_TO_SECTOR.get(symbol)
            if sector:
                sector_counts[sector] = sector_counts.get(sector, 0) + 1

        filtered: list[Recommendation] = []
        skipped = 0
        for recommendation in plan.recommendations:
            if recommendation.action != "BUY":
                filtered.append(recommendation)
                continue

            sector = self.SYMBOL_TO_SECTOR.get(recommendation.symbol)
            if not sector:
                filtered.append(recommendation)
                continue

            current_count = sector_counts.get(sector, 0)
            if current_count >= self.bull_max_symbols_per_sector:
                skipped += 1
                continue

            sector_counts[sector] = current_count + 1
            filtered.append(recommendation)

        if skipped:
            plan.notes.append(
                f"Sector diversification applied in bull mode: capped new ideas at {self.bull_max_symbols_per_sector} per sector."
            )
        plan.recommendations = filtered
        return plan

    def _apply_bull_caution_policy(
        self,
        plan: WeeklyPlan,
        market_data: dict[str, list[OHLCV]],
        portfolio_state: PortfolioState,
    ) -> WeeklyPlan:
        if not portfolio_state.positions:
            return plan

        caution_sells: list[Recommendation] = []
        ma_short = max(self.bull_caution_ma_short, 2)
        ma_long = max(self.bull_caution_ma_long, ma_short + 1)
        ret_lookback = max(self.bull_caution_ret_lookback, 2)

        for symbol in portfolio_state.positions.keys():
            candles = market_data.get(symbol, [])
            if len(candles) < ma_long:
                continue

            closes = [c.close for c in candles]
            current = closes[-1]
            ma_short_value = sum(closes[-ma_short:]) / ma_short
            ma_long_value = sum(closes[-ma_long:]) / ma_long
            past_close = closes[-(ret_lookback + 1)]
            recent_return = (current - past_close) / past_close if past_close else 0.0

            if current >= ma_short_value or current >= ma_long_value or recent_return >= 0:
                continue

            caution_sells.append(
                Recommendation(
                    symbol=symbol,
                    asset_class="stock",
                    action="SELL",
                    buy_zone_low=0.0,
                    buy_zone_high=0.0,
                    stop_loss=0.0,
                    take_profit=0.0,
                    position_target_pct=0.0,
                    rationale_bullets=[
                        "Bull caution exit: short-term trend and breadth weakened together."
                    ],
                )
            )

        if not caution_sells:
            return plan

        sell_symbols = {sell.symbol for sell in caution_sells}
        plan.recommendations = [
            rec for rec in plan.recommendations
            if not (rec.action == "BUY" and rec.symbol in sell_symbols)
        ]
        plan.recommendations.extend(caution_sells)
        plan.force_defensive_exits = True
        plan.max_new_positions = min(
            plan.max_new_positions or self.bull_caution_max_new_positions,
            self.bull_caution_max_new_positions,
        )
        plan.notes.append(
            "Bull caution policy active: trimmed weakening holdings and reduced new entries."
        )
        return plan

    def generate_weekly_plan(
        self,
        market_data: dict[str, list[OHLCV]],
        portfolio_state: PortfolioState,
        config: dict,
    ) -> WeeklyPlan:
        regime = self.detect_regime(market_data)

        if regime == "bear":
            return self._cash_plan(portfolio_state)

        delegate = self.bull_strategy if regime == "bull" else self.sideway_strategy
        plan = delegate.generate_weekly_plan(market_data, portfolio_state, config)
        plan.strategy_id = self.id
        plan.strategy_version = self.version
        plan.market_regime = regime
        if regime == "bull":
            is_strong_bull = self._is_strong_bull(self._last_snapshot)
            bull_caution = self._is_bull_caution(self._last_snapshot)
        else:
            is_strong_bull = False
            bull_caution = False

        if regime == "bull":
            bull_trade_cap = (
                self.bull_max_new_positions
                if is_strong_bull
                else self.bull_transition_max_new_positions
            )
            plan.max_new_positions = bull_trade_cap
            plan = self._restrict_transition_bull_entries(plan, is_strong_bull)
        else:
            plan.max_new_positions = self.sideway_max_new_positions
        plan.allow_symbol_add_ons = False
        plan.max_open_trades_per_symbol = 1
        if regime == "bull":
            plan = self._apply_bull_add_on_policy(plan, portfolio_state)
            plan = self._apply_sector_diversification(plan, portfolio_state, regime)
            if bull_caution:
                plan = self._apply_bull_caution_policy(plan, market_data, portfolio_state)
        plan = self._apply_deployment_policy(plan, portfolio_state, regime)
        plan.notes = [
            f"Regime router selected {regime.upper()} mode.",
            *plan.notes,
        ]
        return plan
