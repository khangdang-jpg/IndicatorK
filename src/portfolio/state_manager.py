"""Portfolio State Manager - Single Source of Truth with Atomic Operations.

Manages portfolio state in JSON format with sequence numbers, locking, and audit trails.
Replaces CSV-based portfolio tracking for consistency between GitHub Actions and Cloudflare Worker.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from src.models import Position, PortfolioState, TradeRecord
from src.portfolio.engine import compute_positions, load_trades

logger = logging.getLogger(__name__)


@dataclass
class StateLock:
    """Represents an active lock on portfolio state."""
    locked_by: str
    locked_at: str
    expires_at: str
    operation: str


@dataclass
class StateMetadata:
    """Metadata about the current portfolio state."""
    last_operation: str = ""
    last_source: str = ""
    github_actions_run_id: Optional[str] = None
    total_fees: float = 0
    cash_adjustments: list = None

    def __post_init__(self):
        if self.cash_adjustments is None:
            self.cash_adjustments = []


@dataclass
class AtomicPortfolioState:
    """Extended portfolio state with atomic operation support."""
    cash: float
    positions: Dict[str, Position]
    total_realized_pnl: float
    last_updated: str
    sequence_number: int
    lock: Optional[StateLock] = None
    metadata: StateMetadata = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = StateMetadata()


class PortfolioStateManager:
    """Manages atomic portfolio state operations."""

    def __init__(self, state_path: str = "data/portfolio_state.json",
                 audit_path: str = "data/trades_log.jsonl"):
        self.state_path = Path(state_path)
        self.audit_path = Path(audit_path)

    def get_state(self) -> AtomicPortfolioState:
        """Read current portfolio state (no locking required for reads)."""
        if not self.state_path.exists():
            logger.warning(f"State file {self.state_path} does not exist. Creating from CSV migration.")
            return self.migrate_from_csv()

        try:
            with open(self.state_path) as f:
                data = json.load(f)

            # Convert positions dict back to Position objects
            positions = {}
            for symbol, pos_data in data.get("positions", {}).items():
                positions[symbol] = Position(
                    symbol=pos_data["symbol"],
                    asset_class=pos_data["asset_class"],
                    qty=pos_data["qty"],
                    avg_cost=pos_data["avg_cost"],
                    current_price=pos_data.get("current_price", pos_data["avg_cost"]),
                    unrealized_pnl=pos_data.get("unrealized_pnl", 0),
                    realized_pnl=pos_data.get("realized_pnl", 0)
                )

            # Convert lock if present
            lock = None
            if data.get("lock"):
                lock_data = data["lock"]
                lock = StateLock(**lock_data)

            # Convert metadata
            metadata = StateMetadata(**data.get("metadata", {}))

            return AtomicPortfolioState(
                cash=data["cash"],
                positions=positions,
                total_realized_pnl=data.get("total_realized_pnl", 0),
                last_updated=data["last_updated"],
                sequence_number=data["sequence_number"],
                lock=lock,
                metadata=metadata
            )

        except Exception as e:
            logger.error(f"Failed to load state from {self.state_path}: {e}")
            raise

    def save_state(self, state: AtomicPortfolioState) -> None:
        """Save portfolio state atomically."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert to dict for JSON serialization
        state_dict = {
            "cash": state.cash,
            "positions": {
                symbol: asdict(position) for symbol, position in state.positions.items()
            },
            "total_realized_pnl": state.total_realized_pnl,
            "last_updated": state.last_updated,
            "sequence_number": state.sequence_number,
            "lock": asdict(state.lock) if state.lock else None,
            "metadata": asdict(state.metadata)
        }

        # Write atomically using temp file
        temp_path = self.state_path.with_suffix('.tmp')
        try:
            with open(temp_path, 'w') as f:
                json.dump(state_dict, f, indent=2, ensure_ascii=False)
            temp_path.replace(self.state_path)
            logger.info(f"Saved state with sequence {state.sequence_number}")
        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            raise e

    def migrate_from_csv(self, trades_path: str = "data/trades.csv") -> AtomicPortfolioState:
        """One-time migration from CSV trades to JSON state."""
        logger.info(f"Migrating portfolio state from {trades_path}")

        # Use existing CSV logic to compute current state
        if Path(trades_path).exists():
            trades = load_trades(trades_path)
            positions, cash = compute_positions(trades)

            # Calculate total realized PnL
            total_realized_pnl = sum(pos.realized_pnl for pos in positions.values())
        else:
            logger.warning(f"Trades file {trades_path} not found. Starting with empty state.")
            positions = {}
            cash = 0
            total_realized_pnl = 0

        # Create initial atomic state
        state = AtomicPortfolioState(
            cash=cash,
            positions=positions,
            total_realized_pnl=total_realized_pnl,
            last_updated=datetime.now(timezone.utc).isoformat(),
            sequence_number=1,
            metadata=StateMetadata(
                last_operation="migration_from_csv",
                last_source="state_manager"
            )
        )

        # Save migrated state
        self.save_state(state)

        # Initialize audit log
        self.append_audit_log({
            "operation": "migration",
            "source": "state_manager",
            "data": {"trades_file": str(trades_path)},
            "sequence_before": 0,
            "sequence_after": 1
        })

        logger.info(f"Migration complete. Cash: {cash:,.0f}, Positions: {len(positions)}")
        return state

    def is_idempotent_operation(self, run_id: str) -> bool:
        """Check if GitHub Actions run was already processed."""
        try:
            state = self.get_state()
            return state.metadata.github_actions_run_id == run_id
        except Exception:
            return False

    def mark_run_processed(self, run_id: str) -> None:
        """Mark a GitHub Actions run as processed."""
        state = self.get_state()
        state.metadata.github_actions_run_id = run_id
        state.last_updated = datetime.now(timezone.utc).isoformat()
        self.save_state(state)

    def append_audit_log(self, entry: dict) -> None:
        """Append operation to audit trail."""
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

        audit_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **entry
        }

        with open(self.audit_path, 'a') as f:
            f.write(json.dumps(audit_entry, ensure_ascii=False) + '\n')

    def to_legacy_portfolio_state(self, current_prices: Optional[dict] = None) -> PortfolioState:
        """Convert atomic state to legacy PortfolioState for backward compatibility."""
        state = self.get_state()

        # Update current prices if provided
        if current_prices:
            for symbol, position in state.positions.items():
                if symbol in current_prices:
                    position.current_price = current_prices[symbol]
                    position.unrealized_pnl = (position.current_price - position.avg_cost) * position.qty

        # Calculate totals
        stock_value = sum(
            pos.current_price * pos.qty
            for pos in state.positions.values()
            if pos.asset_class == "stock"
        )
        bond_fund_value = sum(
            pos.current_price * pos.qty
            for pos in state.positions.values()
            if pos.asset_class in ["bond", "fund"]
        )
        total_unrealized = sum(pos.unrealized_pnl for pos in state.positions.values())

        total_value = state.cash + stock_value + bond_fund_value

        # Calculate allocation percentages
        allocation = {
            "stock_pct": stock_value / total_value if total_value > 0 else 0,
            "bond_fund_pct": bond_fund_value / total_value if total_value > 0 else 0,
            "cash_pct": state.cash / total_value if total_value > 0 else 1.0,
        }

        return PortfolioState(
            positions=state.positions,
            cash=state.cash,
            total_value=total_value,
            allocation=allocation,
            realized_pnl=state.total_realized_pnl,
            unrealized_pnl=total_unrealized
        )