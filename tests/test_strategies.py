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

    def test_regime_router_from_config(self, tmp_path):
        config = tmp_path / "strategy.yml"
        config.write_text("active: regime_router_foundation\nregime_router_foundation:\n  bull_proxy_ret_20: 0.03\n")

        from src.utils.config import get_strategy
        strategy = get_strategy(str(config))
        assert strategy.id == "regime_router_foundation"


class TestRegimeRouterFoundation:
    def test_bear_mode_returns_sell_recommendations_for_held_positions(self):
        from src.strategies.regime_router_foundation import RegimeRouterFoundation

        strategy = RegimeRouterFoundation()
        positions = {
            "HPG": Position("HPG", "stock", 100, 25000, 25000),
            "VCB": Position("VCB", "stock", 50, 80000, 80000),
        }
        portfolio = _make_portfolio(positions=positions, cash=1000000)

        bear_data = {}
        for symbol in ["HPG", "VCB", "FPT", "MBB", "TCB"]:
            candles = []
            base = 100.0
            for i in range(80):
                price = base - i * 1.2
                candles.append(OHLCV(
                    date=date(2024, 1, 1).fromordinal(date(2024, 1, 1).toordinal() + i),
                    open=price,
                    high=price + 0.5,
                    low=price - 0.5,
                    close=price,
                    volume=100000,
                ))
            bear_data[symbol] = candles

        plan = strategy.generate_weekly_plan(bear_data, portfolio, {})
        assert plan.market_regime == "bear"
        assert {rec.action for rec in plan.recommendations} == {"SELL"}
        assert plan.max_new_positions == 0
        assert plan.force_defensive_exits is True

    def test_sideway_mode_sets_higher_trade_cap(self):
        from src.strategies.regime_router_foundation import RegimeRouterFoundation

        class ForcedSidewayRouter(RegimeRouterFoundation):
            def detect_regime(self, market_data):
                return "sideway"

        strategy = ForcedSidewayRouter({"sideway_max_new_positions": 6})
        portfolio = _make_portfolio()
        market_data = _make_market_data()

        plan = strategy.generate_weekly_plan(market_data, portfolio, {})
        assert plan.max_new_positions == 6
        assert plan.allow_symbol_add_ons is False
        assert plan.max_open_trades_per_symbol == 1

    def test_weak_bull_mode_uses_transition_trade_cap(self):
        from src.strategies.regime_router_foundation import RegimeRouterFoundation
        from src.models import WeeklyPlan

        class ForcedWeakBullRouter(RegimeRouterFoundation):
            def detect_regime(self, market_data):
                self._last_snapshot = self._last_snapshot.__class__(
                    proxy_ret_20=0.03,
                    proxy_ret_60=0.08,
                    breadth_20=0.62,
                    breadth_50=0.58,
                    avg_ret_20=0.03,
                    avg_daily_vol_20=0.016,
                )
                return "bull"

        class FakeBullDelegate:
            def generate_weekly_plan(self, market_data, portfolio_state, config):
                return WeeklyPlan(
                    generated_at="2026-04-12T00:00:00",
                    strategy_id="institutional_intraweek_enhanced",
                    strategy_version="test",
                    allocation_targets={"stock": 0.9, "bond_fund": 0.1},
                    recommendations=[],
                    market_regime="bull",
                    notes=[],
                )

        strategy = ForcedWeakBullRouter({"bull_transition_max_new_positions": 5})
        strategy.bull_strategy = FakeBullDelegate()

        plan = strategy.generate_weekly_plan(_make_market_data(), _make_portfolio(), {})
        assert plan.max_new_positions == 5

    def test_strong_bull_mode_keeps_selective_trade_cap(self):
        from src.strategies.regime_router_foundation import RegimeRouterFoundation
        from src.models import Recommendation, WeeklyPlan

        class ForcedStrongBullRouter(RegimeRouterFoundation):
            def detect_regime(self, market_data):
                self._last_snapshot = self._last_snapshot.__class__(
                    proxy_ret_20=0.08,
                    proxy_ret_60=0.14,
                    breadth_20=0.80,
                    breadth_50=0.75,
                    avg_ret_20=0.08,
                    avg_daily_vol_20=0.010,
                )
                return "bull"

        class FakeBullDelegate:
            def generate_weekly_plan(self, market_data, portfolio_state, config):
                rec = Recommendation(
                    symbol="TCB",
                    asset_class="stock",
                    action="BUY",
                    buy_zone_low=25000,
                    buy_zone_high=25000,
                    stop_loss=23500,
                    take_profit=29000,
                    position_target_pct=0.20,
                    rationale_bullets=["Bull breakout candidate"],
                    entry_type="breakout",
                    breakout_level=25000,
                    entry_price=25000,
                )
                return WeeklyPlan(
                    generated_at="2026-04-12T00:00:00",
                    strategy_id="institutional_intraweek_enhanced",
                    strategy_version="test",
                    allocation_targets={"stock": 0.9, "bond_fund": 0.1},
                    recommendations=[rec],
                    market_regime="bull",
                    notes=[],
                )

        strategy = ForcedStrongBullRouter(
            {
                "bull_max_new_positions": 4,
                "bull_transition_max_new_positions": 5,
            }
        )
        strategy.bull_strategy = FakeBullDelegate()

        plan = strategy.generate_weekly_plan(_make_market_data(), _make_portfolio(), {})
        assert plan.max_new_positions == 4
        assert plan.recommendations[0].entry_type == "breakout"

    def test_weak_bull_downgrades_breakout_entries_to_pullbacks(self):
        from src.strategies.regime_router_foundation import RegimeRouterFoundation
        from src.models import Recommendation, WeeklyPlan

        class ForcedWeakBullRouter(RegimeRouterFoundation):
            def detect_regime(self, market_data):
                self._last_snapshot = self._last_snapshot.__class__(
                    proxy_ret_20=0.03,
                    proxy_ret_60=0.08,
                    breadth_20=0.62,
                    breadth_50=0.58,
                    avg_ret_20=0.03,
                    avg_daily_vol_20=0.016,
                )
                return "bull"

        class FakeBullDelegate:
            def generate_weekly_plan(self, market_data, portfolio_state, config):
                rec = Recommendation(
                    symbol="TCB",
                    asset_class="stock",
                    action="BUY",
                    buy_zone_low=25000,
                    buy_zone_high=25000,
                    stop_loss=23500,
                    take_profit=29000,
                    position_target_pct=0.20,
                    rationale_bullets=["Bull breakout candidate"],
                    entry_type="breakout",
                    breakout_level=25000,
                    entry_price=25000,
                )
                return WeeklyPlan(
                    generated_at="2026-04-12T00:00:00",
                    strategy_id="institutional_intraweek_enhanced",
                    strategy_version="test",
                    allocation_targets={"stock": 0.9, "bond_fund": 0.1},
                    recommendations=[rec],
                    market_regime="bull",
                    notes=[],
                )

        strategy = ForcedWeakBullRouter({"bull_transition_max_new_positions": 5})
        strategy.bull_strategy = FakeBullDelegate()

        plan = strategy.generate_weekly_plan(_make_market_data(), _make_portfolio(), {})
        assert plan.max_new_positions == 5
        assert plan.recommendations[0].entry_type == "pullback"
        assert plan.recommendations[0].breakout_level == 0.0

    def test_bull_mode_enables_add_ons_for_strong_existing_winners(self):
        from src.strategies.regime_router_foundation import RegimeRouterFoundation
        from src.models import Recommendation, WeeklyPlan

        class ForcedBullRouter(RegimeRouterFoundation):
            def detect_regime(self, market_data):
                self._last_snapshot = self._last_snapshot.__class__(
                    proxy_ret_20=0.08,
                    proxy_ret_60=0.14,
                    breadth_20=0.80,
                    breadth_50=0.75,
                    avg_ret_20=0.08,
                    avg_daily_vol_20=0.010,
                )
                return "bull"

        strategy = ForcedBullRouter(
            {
                "bull_allow_add_ons": True,
                "bull_max_open_trades_per_symbol": 2,
                "bull_add_on_size_scale": 0.5,
                "bull_add_on_min_conviction": 0.8,
            }
        )
        held_buy = Recommendation(
            symbol="HPG",
            asset_class="stock",
            action="BUY",
            buy_zone_low=25000,
            buy_zone_high=25000,
            stop_loss=23500,
            take_profit=28000,
            position_target_pct=0.20,
            rationale_bullets=["🚀 MOMENTUM BREAKOUT | Regime: TRENDING_BULL"],
        )
        held_buy.conviction_score = 0.95

        class FakeBullDelegate:
            def generate_weekly_plan(self, market_data, portfolio_state, config):
                return WeeklyPlan(
                    generated_at="2026-04-12T00:00:00",
                    strategy_id="institutional_intraweek_enhanced",
                    strategy_version="test",
                    allocation_targets={"stock": 0.9, "bond_fund": 0.1},
                    recommendations=[held_buy],
                    market_regime="bull",
                    notes=[],
                )

        strategy.bull_strategy = FakeBullDelegate()
        portfolio = _make_portfolio(
            positions={"HPG": Position("HPG", "stock", 100, 25000, 25000)},
            cash=1000000,
        )
        market_data = _make_market_data()

        plan = strategy.generate_weekly_plan(market_data, portfolio, {})

        held_buy = next((rec for rec in plan.recommendations if rec.symbol == "HPG" and rec.action == "BUY"), None)
        assert plan.allow_symbol_add_ons is True
        assert plan.max_open_trades_per_symbol == 2
        assert held_buy is not None
        assert held_buy.position_target_pct == 0.10
        assert any("Bull add-on enabled" in bullet for bullet in held_buy.rationale_bullets)

    def test_bull_mode_scales_deployment_when_cash_is_idle(self):
        from src.strategies.regime_router_foundation import RegimeRouterFoundation
        from src.models import Recommendation, WeeklyPlan

        class ForcedBullRouter(RegimeRouterFoundation):
            def detect_regime(self, market_data):
                self._last_snapshot = self._last_snapshot.__class__(
                    proxy_ret_20=0.06,
                    proxy_ret_60=0.12,
                    breadth_20=0.75,
                    breadth_50=0.70,
                    avg_ret_20=0.06,
                    avg_daily_vol_20=0.009,
                )
                return "bull"

        rec_1 = Recommendation(
            symbol="HPG",
            asset_class="stock",
            action="BUY",
            buy_zone_low=25000,
            buy_zone_high=25000,
            stop_loss=23500,
            take_profit=28000,
            position_target_pct=0.12,
            rationale_bullets=["Bull candidate 1"],
        )
        rec_2 = Recommendation(
            symbol="FPT",
            asset_class="stock",
            action="BUY",
            buy_zone_low=110000,
            buy_zone_high=110000,
            stop_loss=103000,
            take_profit=123000,
            position_target_pct=0.12,
            rationale_bullets=["Bull candidate 2"],
        )

        class FakeBullDelegate:
            def generate_weekly_plan(self, market_data, portfolio_state, config):
                return WeeklyPlan(
                    generated_at="2026-04-12T00:00:00",
                    strategy_id="institutional_intraweek_enhanced",
                    strategy_version="test",
                    allocation_targets={"stock": 0.9, "bond_fund": 0.1},
                    recommendations=[rec_1, rec_2],
                    market_regime="bull",
                    notes=[],
                )

        strategy = ForcedBullRouter(
            {
                "bull_low_vol_stock_target": 0.92,
                "bull_position_target_cap": 0.30,
                "bull_max_deployment_scale": 1.40,
            }
        )
        strategy.bull_strategy = FakeBullDelegate()

        plan = strategy.generate_weekly_plan(_make_market_data(), _make_portfolio(cash=20_000_000), {})
        buy_sizes = [rec.position_target_pct for rec in plan.recommendations if rec.action == "BUY"]

        assert buy_sizes == pytest.approx([0.168, 0.168])
        assert plan.allocation_targets["stock"] == pytest.approx(0.92)
        assert any("Vol-targeted deployment" in note for note in plan.notes)

    def test_sideway_mode_scales_deployment_with_tighter_cap(self):
        from src.strategies.regime_router_foundation import RegimeRouterFoundation
        from src.models import Recommendation, WeeklyPlan

        class ForcedSidewayRouter(RegimeRouterFoundation):
            def detect_regime(self, market_data):
                self._last_snapshot = self._last_snapshot.__class__(
                    proxy_ret_20=0.00,
                    proxy_ret_60=0.02,
                    breadth_20=0.55,
                    breadth_50=0.52,
                    avg_ret_20=0.00,
                    avg_daily_vol_20=0.010,
                )
                return "sideway"

        rec = Recommendation(
            symbol="MWG",
            asset_class="stock",
            action="BUY",
            buy_zone_low=45000,
            buy_zone_high=45000,
            stop_loss=43000,
            take_profit=49500,
            position_target_pct=0.10,
            rationale_bullets=["Sideway candidate"],
        )

        class FakeSidewayDelegate:
            def generate_weekly_plan(self, market_data, portfolio_state, config):
                return WeeklyPlan(
                    generated_at="2026-04-12T00:00:00",
                    strategy_id="institutional_intraweek_enhanced",
                    strategy_version="test",
                    allocation_targets={"stock": 0.7, "bond_fund": 0.3},
                    recommendations=[rec],
                    market_regime="sideway",
                    notes=[],
                )

        strategy = ForcedSidewayRouter(
            {
                "sideway_low_vol_stock_target": 0.82,
                "sideway_position_target_cap": 0.18,
                "sideway_max_deployment_scale": 1.25,
            }
        )
        strategy.sideway_strategy = FakeSidewayDelegate()

        plan = strategy.generate_weekly_plan(_make_market_data(), _make_portfolio(cash=20_000_000), {})
        buy = next(rec for rec in plan.recommendations if rec.action == "BUY")

        assert buy.position_target_pct == pytest.approx(0.125)
        assert plan.allocation_targets["stock"] == pytest.approx(0.82)

    def test_bull_mode_limits_same_sector_exposure(self):
        from src.strategies.regime_router_foundation import RegimeRouterFoundation
        from src.models import Recommendation, WeeklyPlan

        class ForcedBullRouter(RegimeRouterFoundation):
            def detect_regime(self, market_data):
                self._last_snapshot = self._last_snapshot.__class__(
                    proxy_ret_20=0.06,
                    proxy_ret_60=0.12,
                    breadth_20=0.75,
                    breadth_50=0.70,
                    avg_ret_20=0.06,
                    avg_daily_vol_20=0.010,
                )
                return "bull"

        bank_names = ["VCB", "MBB", "ACB"]
        recs = []
        for symbol in bank_names:
            rec = Recommendation(
                symbol=symbol,
                asset_class="stock",
                action="BUY",
                buy_zone_low=25000,
                buy_zone_high=25000,
                stop_loss=23500,
                take_profit=28000,
                position_target_pct=0.12,
                rationale_bullets=[f"Bull candidate {symbol}"],
                entry_type="pullback",
            )
            rec.conviction_score = 0.95
            recs.append(rec)

        class FakeBullDelegate:
            def generate_weekly_plan(self, market_data, portfolio_state, config):
                return WeeklyPlan(
                    generated_at="2026-04-12T00:00:00",
                    strategy_id="institutional_intraweek_enhanced",
                    strategy_version="test",
                    allocation_targets={"stock": 0.9, "bond_fund": 0.1},
                    recommendations=recs,
                    market_regime="bull",
                    notes=[],
                )

        strategy = ForcedBullRouter({"bull_max_symbols_per_sector": 2})
        strategy.bull_strategy = FakeBullDelegate()
        plan = strategy.generate_weekly_plan(_make_market_data(), _make_portfolio(cash=20_000_000), {})

        buy_symbols = [rec.symbol for rec in plan.recommendations if rec.action == "BUY"]
        assert len(buy_symbols) == 2
        assert buy_symbols == ["VCB", "MBB"]
        assert any("Sector diversification applied" in note for note in plan.notes)
