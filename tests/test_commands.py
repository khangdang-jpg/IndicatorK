"""Tests for Telegram command parsing."""

import os
import tempfile

import pytest

from src.models import TradeRecord
from src.telegram.commands import handle_command


@pytest.fixture
def trades_csv(tmp_path, monkeypatch):
    """Create a temp trades.csv and patch the default path."""
    csv_file = tmp_path / "trades.csv"
    csv_file.write_text("timestamp_iso,asset_class,symbol,side,qty,price,fee,note\n")
    monkeypatch.setattr("src.telegram.commands.append_trade",
                        lambda trade, path=None: _append_to(csv_file, trade))
    monkeypatch.setattr("src.portfolio.engine.Path",
                        lambda p: tmp_path / os.path.basename(p) if "trades" in str(p) else __import__("pathlib").Path(p))
    return csv_file


def _append_to(csv_file, trade):
    """Helper to append trade to temp file."""
    import csv
    with open(csv_file, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            trade.timestamp_iso, trade.asset_class, trade.symbol,
            trade.side, trade.qty, trade.price, trade.fee, trade.note,
        ])


class TestBuyCommand:
    def test_basic_buy(self, trades_csv):
        result = handle_command("/buy HPG 100 25000")
        assert "Recorded BUY HPG" in result
        assert "100" in result
        assert "25,000" in result

    def test_buy_with_options(self, trades_csv):
        result = handle_command("/buy VNM 50 80000 asset=stock fee=100 note=test")
        assert "Recorded BUY VNM" in result
        assert "Fee: 100" in result

    def test_buy_bond(self, trades_csv):
        result = handle_command("/buy TCBF 1000 15000 asset=fund")
        assert "Recorded BUY TCBF" in result
        assert "fund" in result

    def test_buy_missing_args(self, trades_csv):
        result = handle_command("/buy HPG")
        assert "Usage" in result

    def test_buy_invalid_symbol(self, trades_csv):
        result = handle_command("/buy hp@g 100 25000")
        assert "error" in result.lower() or "Invalid" in result

    def test_buy_negative_qty(self, trades_csv):
        result = handle_command("/buy HPG -10 25000")
        assert "error" in result.lower() or "positive" in result.lower()

    def test_buy_zero_price(self, trades_csv):
        result = handle_command("/buy HPG 100 0")
        assert "error" in result.lower() or "positive" in result.lower()

    def test_buy_invalid_asset(self, trades_csv):
        result = handle_command("/buy HPG 100 25000 asset=crypto")
        assert "Error" in result


class TestSellCommand:
    def test_basic_sell(self, trades_csv):
        result = handle_command("/sell HPG 50 26000")
        assert "Recorded SELL HPG" in result

    def test_sell_with_fee(self, trades_csv):
        result = handle_command("/sell HPG 50 26000 fee=50")
        assert "Fee: 50" in result


class TestSetcashCommand:
    def test_setcash(self, trades_csv):
        result = handle_command("/setcash 10000000")
        assert "10,000,000" in result

    def test_setcash_missing_amount(self, trades_csv):
        result = handle_command("/setcash")
        assert "Usage" in result

    def test_setcash_negative(self, trades_csv):
        result = handle_command("/setcash -1000")
        assert "error" in result.lower() or "negative" in result.lower()

    def test_setcash_invalid(self, trades_csv):
        result = handle_command("/setcash abc")
        assert "error" in result.lower()


class TestOtherCommands:
    def test_help(self):
        result = handle_command("/help")
        assert "/buy" in result
        assert "/sell" in result
        assert "/setcash" in result
        assert "/status" in result
        assert "/plan" in result

    def test_unknown_command(self):
        result = handle_command("/unknown")
        assert "Unknown command" in result

    def test_status_empty_portfolio(self):
        result = handle_command("/status")
        assert "Portfolio" in result or "No open positions" in result
