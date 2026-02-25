"""S2: Allocation-first 50/50 stock vs bond+fund rebalance strategy."""

from __future__ import annotations

import logging
from datetime import datetime

from src.models import OHLCV, PortfolioState, Recommendation, WeeklyPlan
from src.strategies.base import Strategy

logger = logging.getLogger(__name__)


class Rebalance5050Strategy(Strategy):

    def __init__(self, params: dict | None = None):
        params = params or {}
        self.stock_target = params.get("stock_target", 0.50)
        self.bond_fund_target = params.get("bond_fund_target", 0.50)
        self.drift_threshold = params.get("drift_threshold", 0.05)

    @property
    def id(self) -> str:
        return "rebalance_50_50"

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
        alloc = portfolio_state.allocation

        stock_pct = alloc.get("stock_pct", 0)
        bond_fund_pct = alloc.get("bond_fund_pct", 0)

        stock_drift = stock_pct - self.stock_target
        bond_fund_drift = bond_fund_pct - self.bond_fund_target

        needs_rebalance = (
            abs(stock_drift) > self.drift_threshold
            or abs(bond_fund_drift) > self.drift_threshold
        )

        notes = [
            f"Target: {self.stock_target:.0%} stock / {self.bond_fund_target:.0%} bond+fund",
            f"Current: {stock_pct:.1%} stock / {bond_fund_pct:.1%} bond+fund / {alloc.get('cash_pct', 0):.1%} cash",
            f"Drift threshold: {self.drift_threshold:.0%}",
        ]

        if needs_rebalance:
            notes.append(
                f"Rebalance needed: stock drift {stock_drift:+.1%}, "
                f"bond+fund drift {bond_fund_drift:+.1%}"
            )
        else:
            notes.append("No rebalance needed — within drift threshold")

        # Generate recommendations for held positions
        for sym, pos in portfolio_state.positions.items():
            candles = market_data.get(sym, [])
            current = pos.current_price
            if current <= 0 and candles:
                current = candles[-1].close

            if current <= 0:
                continue

            # Conservative levels
            buy_zone_low = round(current * 0.95, 2)
            buy_zone_high = round(current * 0.98, 2)
            stop_loss = round(current * 0.90, 2)
            take_profit = round(current * 1.15, 2)

            if needs_rebalance and pos.asset_class == "stock" and stock_drift > 0:
                action = "REDUCE"
                rationale = [
                    f"Stock overweight by {stock_drift:.1%}",
                    "Reduce to rebalance toward target allocation",
                ]
            elif needs_rebalance and pos.asset_class != "stock" and bond_fund_drift > 0:
                action = "REDUCE"
                rationale = [
                    f"Bond+fund overweight by {bond_fund_drift:.1%}",
                    "Reduce to rebalance toward target allocation",
                ]
            else:
                action = "HOLD"
                rationale = ["Position within allocation targets"]

            recommendations.append(Recommendation(
                symbol=sym,
                asset_class=pos.asset_class,
                action=action,
                buy_zone_low=buy_zone_low,
                buy_zone_high=buy_zone_high,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_target_pct=0,
                rationale_bullets=rationale,
            ))

        # If underweight stocks and rebalance needed, suggest BUY from watchlist
        if needs_rebalance and stock_drift < -self.drift_threshold:
            buy_candidates = [
                sym for sym in market_data
                if sym not in portfolio_state.positions
            ]
            max_pos = config.get("position", {}).get("max_single_position_pct", 0.15)

            for sym in buy_candidates[:5]:
                candles = market_data.get(sym, [])
                if not candles:
                    continue
                current = candles[-1].close
                recommendations.append(Recommendation(
                    symbol=sym,
                    asset_class="stock",
                    action="BUY",
                    buy_zone_low=round(current * 0.95, 2),
                    buy_zone_high=round(current * 0.98, 2),
                    stop_loss=round(current * 0.90, 2),
                    take_profit=round(current * 1.15, 2),
                    position_target_pct=max_pos,
                    rationale_bullets=[
                        f"Stock underweight by {abs(stock_drift):.1%}",
                        "Buy to rebalance toward target allocation",
                    ],
                ))

        action_order = {"BUY": 0, "HOLD": 1, "REDUCE": 2, "SELL": 3}
        recommendations.sort(key=lambda r: action_order.get(r.action, 99))

        return WeeklyPlan(
            generated_at=datetime.utcnow().isoformat(),
            strategy_id=self.id,
            strategy_version=self.version,
            allocation_targets={
                "stock": self.stock_target,
                "bond_fund": self.bond_fund_target,
            },
            recommendations=recommendations,
            notes=notes,
        )
