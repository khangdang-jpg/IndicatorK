"""Portfolio engine — parse trades, compute positions, PnL, allocation."""

from __future__ import annotations

import csv
import logging
import os
from datetime import datetime
from pathlib import Path

from src.models import OHLCV, PortfolioState, Position, TradeRecord
from src.utils.csv_safety import sanitize_csv_field, validate_symbol

logger = logging.getLogger(__name__)

# Flag to enable atomic state system
USE_ATOMIC_STATE = os.environ.get("USE_ATOMIC_STATE", "true").lower() == "true"

TRADES_HEADER = "timestamp_iso,asset_class,symbol,side,qty,price,fee,note"


def load_trades(path: str = "data/trades.csv") -> list[TradeRecord]:
    """Parse trades.csv into TradeRecord list."""
    p = Path(path)
    if not p.exists():
        logger.warning("Trades file not found: %s", path)
        return []

    records = []
    with open(p, newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):
            try:
                records.append(TradeRecord(
                    timestamp_iso=row["timestamp_iso"].strip(),
                    asset_class=row["asset_class"].strip().lower(),
                    symbol=row["symbol"].strip().upper(),
                    side=row["side"].strip().upper(),
                    qty=float(row["qty"]),
                    price=float(row["price"]),
                    fee=float(row.get("fee", 0) or 0),
                    note=row.get("note", "").strip(),
                ))
            except (KeyError, ValueError) as e:
                logger.warning("Skipping invalid trade row %d: %s", i, e)
    return records


def append_trade(trade: TradeRecord, path: str = "data/trades.csv") -> None:
    """Append a single trade to the CSV file."""
    p = Path(path)
    write_header = not p.exists() or p.stat().st_size == 0
    with open(p, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(TRADES_HEADER.split(","))
        writer.writerow([
            sanitize_csv_field(trade.timestamp_iso),
            sanitize_csv_field(trade.asset_class),
            sanitize_csv_field(trade.symbol),
            sanitize_csv_field(trade.side),
            trade.qty,
            trade.price,
            trade.fee,
            sanitize_csv_field(trade.note),
        ])


def compute_positions(trades: list[TradeRecord]) -> tuple[dict[str, Position], float]:
    """Compute current positions and cash from trade history.

    Returns (positions_dict, cash_balance).
    Uses weighted average cost basis.
    """
    positions: dict[str, Position] = {}
    cash = 0.0

    for t in trades:
        if t.side == "CASH":
            cash = t.price
            continue

        key = t.symbol
        if key not in positions:
            positions[key] = Position(
                symbol=t.symbol,
                asset_class=t.asset_class,
                qty=0,
                avg_cost=0,
            )
        pos = positions[key]

        if t.side == "BUY":
            total_cost = pos.avg_cost * pos.qty + t.price * t.qty
            pos.qty += t.qty
            pos.avg_cost = total_cost / pos.qty if pos.qty > 0 else 0
            cash -= t.price * t.qty + t.fee
        elif t.side == "SELL":
            if pos.qty > 0:
                realized = (t.price - pos.avg_cost) * min(t.qty, pos.qty)
                pos.realized_pnl += realized
                pos.qty -= t.qty
                cash += t.price * t.qty - t.fee
            if pos.qty <= 0:
                pos.qty = 0

        pos.asset_class = t.asset_class

    # Remove closed positions
    positions = {k: v for k, v in positions.items() if v.qty > 0}
    return positions, cash


def get_atomic_portfolio_state(current_prices: dict[str, float] | None = None) -> PortfolioState:
    """Get portfolio state from atomic JSON store (new system)."""
    from src.portfolio.state_manager import PortfolioStateManager

    manager = PortfolioStateManager()
    return manager.to_legacy_portfolio_state(current_prices)


def get_portfolio_state(
    trades_path: str = "data/trades.csv",
    current_prices: dict[str, float] | None = None,
) -> PortfolioState:
    """Build complete portfolio state from trades and current prices.

    Uses atomic JSON state when USE_ATOMIC_STATE=true, falls back to CSV otherwise.
    """
    # Use atomic state system if enabled and available
    if USE_ATOMIC_STATE:
        try:
            return get_atomic_portfolio_state(current_prices)
        except Exception as e:
            logger.warning(f"Failed to load atomic state, falling back to CSV: {e}")

    # Fallback to CSV-based system
    trades = load_trades(trades_path)
    positions, cash = compute_positions(trades)

    if current_prices is None:
        current_prices = {}

    # Update current prices and compute unrealized PnL
    total_unrealized = 0.0
    total_realized = 0.0
    stock_value = 0.0
    bond_fund_value = 0.0

    for sym, pos in positions.items():
        # Use current price if available, otherwise use last trade price (avg_cost)
        price = current_prices.get(sym, pos.avg_cost)
        pos.current_price = price
        pos.unrealized_pnl = (price - pos.avg_cost) * pos.qty
        total_unrealized += pos.unrealized_pnl
        total_realized += pos.realized_pnl

        market_value = price * pos.qty
        if pos.asset_class == "stock":
            stock_value += market_value
        else:  # bond or fund
            bond_fund_value += market_value

    total_value = stock_value + bond_fund_value + cash

    allocation = {
        "stock_pct": stock_value / total_value if total_value > 0 else 0,
        "bond_fund_pct": bond_fund_value / total_value if total_value > 0 else 0,
        "cash_pct": cash / total_value if total_value > 0 else 1.0,
    }

    return PortfolioState(
        positions=positions,
        cash=cash,
        total_value=total_value,
        allocation=allocation,
        unrealized_pnl=total_unrealized,
        realized_pnl=total_realized,
    )


def compute_portfolio_snapshot(state: PortfolioState) -> dict:
    """Create a snapshot row for portfolio_weekly.csv."""
    stock_val = 0.0
    bond_fund_val = 0.0
    for pos in state.positions.values():
        mv = pos.current_price * pos.qty
        if pos.asset_class == "stock":
            stock_val += mv
        else:
            bond_fund_val += mv

    return {
        "date_iso": datetime.utcnow().strftime("%Y-%m-%d"),
        "total_value": round(state.total_value, 2),
        "stock_value": round(stock_val, 2),
        "bond_fund_value": round(bond_fund_val, 2),
        "cash_value": round(state.cash, 2),
        "realized_pnl": round(state.realized_pnl, 2),
        "unrealized_pnl": round(state.unrealized_pnl, 2),
    }


WEEKLY_SNAPSHOT_HEADER = (
    "date_iso,total_value,stock_value,bond_fund_value,"
    "cash_value,realized_pnl,unrealized_pnl"
)


def append_portfolio_snapshot(
    state: PortfolioState, path: str = "data/portfolio_weekly.csv"
) -> None:
    """Append a weekly portfolio value snapshot."""
    p = Path(path)
    write_header = not p.exists() or p.stat().st_size == 0
    snap = compute_portfolio_snapshot(state)
    with open(p, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(WEEKLY_SNAPSHOT_HEADER.split(","))
        writer.writerow([
            snap["date_iso"],
            snap["total_value"],
            snap["stock_value"],
            snap["bond_fund_value"],
            snap["cash_value"],
            snap["realized_pnl"],
            snap["unrealized_pnl"],
        ])


def load_portfolio_snapshots(
    path: str = "data/portfolio_weekly.csv",
) -> list[dict]:
    """Load portfolio weekly snapshots for guardrails metrics."""
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    with open(p, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                rows.append({
                    "date_iso": row["date_iso"],
                    "total_value": float(row["total_value"]),
                    "stock_value": float(row["stock_value"]),
                    "bond_fund_value": float(row["bond_fund_value"]),
                    "cash_value": float(row["cash_value"]),
                    "realized_pnl": float(row["realized_pnl"]),
                    "unrealized_pnl": float(row["unrealized_pnl"]),
                })
            except (KeyError, ValueError) as e:
                logger.warning("Skipping invalid snapshot row: %s", e)
    return rows
