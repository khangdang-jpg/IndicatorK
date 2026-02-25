"""Tests for portfolio engine — positions, PnL, allocation."""

import csv
import tempfile
from pathlib import Path

import pytest

from src.models import PortfolioState, Position, TradeRecord
from src.portfolio.engine import (
    append_portfolio_snapshot,
    append_trade,
    compute_positions,
    compute_portfolio_snapshot,
    get_portfolio_state,
    load_portfolio_snapshots,
    load_trades,
)


@pytest.fixture
def trades_file(tmp_path):
    p = tmp_path / "trades.csv"
    p.write_text("timestamp_iso,asset_class,symbol,side,qty,price,fee,note\n")
    return str(p)


class TestLoadTrades:
    def test_empty_file(self, trades_file):
        trades = load_trades(trades_file)
        assert trades == []

    def test_load_trades(self, trades_file):
        with open(trades_file, "a") as f:
            f.write("2025-01-01T00:00:00,stock,HPG,BUY,100,25000,50,test\n")
        trades = load_trades(trades_file)
        assert len(trades) == 1
        assert trades[0].symbol == "HPG"
        assert trades[0].qty == 100
        assert trades[0].price == 25000

    def test_missing_file(self, tmp_path):
        trades = load_trades(str(tmp_path / "nonexistent.csv"))
        assert trades == []


class TestComputePositions:
    def test_single_buy(self):
        trades = [
            TradeRecord("2025-01-01", "stock", "HPG", "BUY", 100, 25000, 0, ""),
        ]
        positions, cash = compute_positions(trades)
        assert "HPG" in positions
        assert positions["HPG"].qty == 100
        assert positions["HPG"].avg_cost == 25000
        assert cash == -2500000  # 100 * 25000

    def test_buy_then_sell(self):
        trades = [
            TradeRecord("2025-01-01", "stock", "HPG", "BUY", 100, 25000, 0, ""),
            TradeRecord("2025-01-02", "stock", "HPG", "SELL", 50, 27000, 0, ""),
        ]
        positions, cash = compute_positions(trades)
        assert positions["HPG"].qty == 50
        assert positions["HPG"].avg_cost == 25000
        assert positions["HPG"].realized_pnl == (27000 - 25000) * 50

    def test_sell_all(self):
        trades = [
            TradeRecord("2025-01-01", "stock", "HPG", "BUY", 100, 25000, 0, ""),
            TradeRecord("2025-01-02", "stock", "HPG", "SELL", 100, 27000, 0, ""),
        ]
        positions, cash = compute_positions(trades)
        assert "HPG" not in positions  # closed position removed

    def test_multiple_buys_avg_cost(self):
        trades = [
            TradeRecord("2025-01-01", "stock", "HPG", "BUY", 100, 20000, 0, ""),
            TradeRecord("2025-01-02", "stock", "HPG", "BUY", 100, 30000, 0, ""),
        ]
        positions, cash = compute_positions(trades)
        assert positions["HPG"].qty == 200
        assert positions["HPG"].avg_cost == 25000  # weighted avg

    def test_setcash(self):
        trades = [
            TradeRecord("2025-01-01", "fund", "CASH", "CASH", 1, 10000000, 0, ""),
        ]
        positions, cash = compute_positions(trades)
        assert cash == 10000000
        assert len(positions) == 0

    def test_buy_with_fees(self):
        trades = [
            TradeRecord("2025-01-01", "stock", "HPG", "BUY", 100, 25000, 500, ""),
        ]
        positions, cash = compute_positions(trades)
        assert cash == -(100 * 25000 + 500)

    def test_mixed_asset_classes(self):
        trades = [
            TradeRecord("2025-01-01", "fund", "CASH", "CASH", 1, 20000000, 0, ""),
            TradeRecord("2025-01-01", "stock", "HPG", "BUY", 100, 25000, 0, ""),
            TradeRecord("2025-01-01", "bond", "TCBF", "BUY", 1000, 15000, 0, ""),
        ]
        positions, cash = compute_positions(trades)
        assert positions["HPG"].asset_class == "stock"
        assert positions["TCBF"].asset_class == "bond"


class TestPortfolioState:
    def test_empty_portfolio(self, trades_file):
        state = get_portfolio_state(trades_file)
        assert state.total_value == 0
        assert state.cash == 0
        assert len(state.positions) == 0

    def test_with_prices(self, trades_file):
        with open(trades_file, "a") as f:
            f.write("2025-01-01T00:00:00,fund,CASH,CASH,1,10000000,0,setcash\n")
            f.write("2025-01-01T00:00:00,stock,HPG,BUY,100,25000,0,\n")
        state = get_portfolio_state(trades_file, current_prices={"HPG": 27000})
        assert state.positions["HPG"].current_price == 27000
        assert state.positions["HPG"].unrealized_pnl == (27000 - 25000) * 100
        assert state.total_value > 0

    def test_allocation_calc(self, trades_file):
        with open(trades_file, "a") as f:
            f.write("2025-01-01T00:00:00,fund,CASH,CASH,1,5000000,0,setcash\n")
            f.write("2025-01-01T00:00:00,stock,HPG,BUY,100,25000,0,\n")
            f.write("2025-01-01T00:00:00,bond,TCBF,BUY,100,15000,0,\n")
        state = get_portfolio_state(
            trades_file, current_prices={"HPG": 25000, "TCBF": 15000}
        )
        assert 0 < state.allocation["stock_pct"] < 1
        assert 0 < state.allocation["bond_fund_pct"] < 1
        assert 0 < state.allocation["cash_pct"] < 1
        total = (
            state.allocation["stock_pct"]
            + state.allocation["bond_fund_pct"]
            + state.allocation["cash_pct"]
        )
        assert abs(total - 1.0) < 0.01


class TestPortfolioSnapshot:
    def test_append_and_load(self, tmp_path):
        path = str(tmp_path / "portfolio_weekly.csv")
        state = PortfolioState(
            positions={},
            cash=10000000,
            total_value=10000000,
            allocation={"stock_pct": 0, "bond_fund_pct": 0, "cash_pct": 1.0},
            unrealized_pnl=0,
            realized_pnl=0,
        )
        append_portfolio_snapshot(state, path)
        snapshots = load_portfolio_snapshots(path)
        assert len(snapshots) == 1
        assert snapshots[0]["total_value"] == 10000000
        assert snapshots[0]["cash_value"] == 10000000

    def test_multiple_snapshots(self, tmp_path):
        path = str(tmp_path / "portfolio_weekly.csv")
        for i in range(3):
            state = PortfolioState(
                positions={},
                cash=10000000 + i * 100000,
                total_value=10000000 + i * 100000,
                allocation={"stock_pct": 0, "bond_fund_pct": 0, "cash_pct": 1.0},
                unrealized_pnl=0,
                realized_pnl=0,
            )
            append_portfolio_snapshot(state, path)
        snapshots = load_portfolio_snapshots(path)
        assert len(snapshots) == 3
