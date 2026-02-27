"""Tests for strategy selection from config and plan schema."""

from datetime import date

import pytest

from src.models import OHLCV, PortfolioState, Position


def _make_portfolio(positions=None, cash=10000000):
    positions = positions or {}
    total = cash + sum(p.current_price * p.qty for p in positions.values())
    stock_val = sum(
        p.current_price * p.qty for p in positions.values() if p.asset_class == "stock"
    )
    bf_val = sum(
        p.current_price * p.qty for p in positions.values() if p.asset_class != "stock"
    )
    return PortfolioState(
        positions=positions,
        cash=cash,
        total_value=total,
        allocation={
            "stock_pct": stock_val / total if total else 0,
            "bond_fund_pct": bf_val / total if total else 0,
            "cash_pct": cash / total if total else 1,
        },
        unrealized_pnl=0,
        realized_pnl=0,
    )


def _make_market_data(symbol="HPG", weeks=40):
    """Generate synthetic daily candles for testing."""
    candles = []
    base = 25000
    for i in range(weeks * 5):
        d = date(2024, 1, 1)
        d = date.fromordinal(d.toordinal() + i)
        # Uptrend with noise
        price = base + i * 50
        candles.append(OHLCV(
            date=d,
            open=price,
            high=price + 500,
            low=price - 500,
            close=price + 100,
            volume=100000,
        ))
    return {symbol: candles}


class TestTrendMomentumATR:
    def test_generate_plan_schema(self):
        from src.strategies.trend_momentum_atr import TrendMomentumATRStrategy

        strategy = TrendMomentumATRStrategy()
        assert strategy.id == "trend_momentum_atr"
        assert strategy.version == "2.0.0"

        portfolio = _make_portfolio()
        market_data = _make_market_data()
        config = {"position": {"max_single_position_pct": 0.15, "max_stock_allocation": 0.6}}

        plan = strategy.generate_weekly_plan(market_data, portfolio, config)

        # Validate schema
        d = plan.to_dict()
        assert "generated_at" in d
        assert d["strategy_id"] == "trend_momentum_atr"
        assert "allocation_targets" in d
        assert isinstance(d["recommendations"], list)
        assert isinstance(d["notes"], list)

        for rec in d["recommendations"]:
            assert "symbol" in rec
            assert rec["action"] in ("BUY", "HOLD", "REDUCE", "SELL")
            assert "buy_zone_low" in rec
            assert "buy_zone_high" in rec
            assert "stop_loss" in rec
            assert "take_profit" in rec
            assert "position_target_pct" in rec
            assert "rationale_bullets" in rec

    def test_not_enough_data(self):
        from src.strategies.trend_momentum_atr import TrendMomentumATRStrategy

        strategy = TrendMomentumATRStrategy()
        portfolio = _make_portfolio()
        # Only 5 candles — not enough
        market_data = {"HPG": [
            OHLCV(date(2025, 1, i), 100, 110, 90, 105, 1000)
            for i in range(1, 6)
        ]}
        config = {}
        plan = strategy.generate_weekly_plan(market_data, portfolio, config)
        assert len(plan.recommendations) == 0


class TestRebalance5050:
    def test_generate_plan_schema(self):
        from src.strategies.rebalance_50_50 import Rebalance5050Strategy

        strategy = Rebalance5050Strategy()
        assert strategy.id == "rebalance_50_50"
        assert strategy.version == "1.0.0"

        portfolio = _make_portfolio()
        market_data = _make_market_data()
        config = {"position": {"max_single_position_pct": 0.15}}

        plan = strategy.generate_weekly_plan(market_data, portfolio, config)
        d = plan.to_dict()
        assert d["strategy_id"] == "rebalance_50_50"
        assert "stock" in d["allocation_targets"]
        assert "bond_fund" in d["allocation_targets"]

    def test_rebalance_triggers_on_drift(self):
        from src.strategies.rebalance_50_50 import Rebalance5050Strategy

        strategy = Rebalance5050Strategy(params={"drift_threshold": 0.05})

        # Portfolio is 80% stock, 0% bond, 20% cash — drift > 5%
        positions = {
            "HPG": Position("HPG", "stock", 100, 25000, 25000),
        }
        portfolio = _make_portfolio(positions=positions, cash=500000)

        market_data = _make_market_data()
        config = {"position": {"max_single_position_pct": 0.15}}
        plan = strategy.generate_weekly_plan(market_data, portfolio, config)

        actions = {r.action for r in plan.recommendations}
        # Should recommend REDUCE for overweight stock or BUY for watchlist
        assert len(plan.recommendations) > 0

    def test_no_rebalance_within_threshold(self):
        from src.strategies.rebalance_50_50 import Rebalance5050Strategy

        strategy = Rebalance5050Strategy(params={"drift_threshold": 0.05})

        # Portfolio is roughly balanced
        positions = {
            "HPG": Position("HPG", "stock", 100, 25000, 25000),
            "TCBF": Position("TCBF", "bond", 167, 15000, 15000),
        }
        portfolio = _make_portfolio(positions=positions, cash=5000)

        config = {"position": {"max_single_position_pct": 0.15}}
        plan = strategy.generate_weekly_plan({}, portfolio, config)

        # All held positions should be HOLD
        for rec in plan.recommendations:
            if rec.symbol in ("HPG", "TCBF"):
                assert rec.action == "HOLD"


class TestConfigDrivenStrategy:
    def test_strategy_from_config(self, tmp_path):
        config = tmp_path / "strategy.yml"
        config.write_text("active: rebalance_50_50\nrebalance_50_50:\n  drift_threshold: 0.10\n")

        from src.utils.config import get_strategy
        strategy = get_strategy(str(config))
        assert strategy.id == "rebalance_50_50"

    def test_invalid_strategy_name(self, tmp_path):
        config = tmp_path / "strategy.yml"
        config.write_text("active: nonexistent\n")

        from src.utils.config import get_strategy
        with pytest.raises(ValueError, match="Unknown strategy"):
            get_strategy(str(config))
