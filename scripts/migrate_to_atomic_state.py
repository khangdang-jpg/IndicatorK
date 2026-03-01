#!/usr/bin/env python3
"""Migration script to convert from CSV-based portfolio to atomic JSON state.

This script:
1. Creates portfolio_state.json from current trades.csv
2. Initializes trades_log.jsonl with migration entry
3. Validates the migration by comparing old vs new portfolio calculations

Run this once before enabling USE_ATOMIC_STATE=true.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.portfolio.engine import get_portfolio_state
from src.portfolio.state_manager import PortfolioStateManager
from src.utils.logging_setup import setup_logging
import logging

def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("Starting migration to atomic portfolio state")

    # Initialize state manager (will auto-migrate if no state file exists)
    state_manager = PortfolioStateManager()

    try:
        # Force migration from CSV
        atomic_state = state_manager.migrate_from_csv()
        logger.info("Migration completed successfully")

        # Validation: Compare old CSV method vs new atomic method
        logger.info("Validating migration...")

        # Get state using old CSV method
        csv_state = get_portfolio_state()

        # Get state using new atomic method
        atomic_portfolio_state = state_manager.to_legacy_portfolio_state()

        # Compare key values
        cash_diff = abs(csv_state.cash - atomic_portfolio_state.cash)
        positions_diff = len(csv_state.positions) - len(atomic_portfolio_state.positions)

        logger.info("Validation Results:")
        logger.info(f"  Cash: CSV={csv_state.cash:,.0f}, Atomic={atomic_portfolio_state.cash:,.0f}, Diff={cash_diff:,.0f}")
        logger.info(f"  Positions: CSV={len(csv_state.positions)}, Atomic={len(atomic_portfolio_state.positions)}, Diff={positions_diff}")

        if cash_diff < 1 and positions_diff == 0:
            logger.info("✅ Validation PASSED - Migration is accurate")
            logger.info("\nNext steps:")
            logger.info("1. Set USE_ATOMIC_STATE=true in your environment")
            logger.info("2. Deploy updated Cloudflare Worker")
            logger.info("3. Test with /status and /buy commands")
            return True
        else:
            logger.error("❌ Validation FAILED - Significant differences detected")
            return False

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)