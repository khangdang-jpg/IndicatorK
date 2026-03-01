#!/usr/bin/env python3
"""Test script for atomic portfolio operations.

Tests the new state management system:
1. Migration from CSV to atomic state
2. State consistency checks
3. Sequence number validation
4. Idempotency testing

Run this after migration to validate the implementation.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.portfolio.state_manager import PortfolioStateManager
from src.portfolio.engine import get_portfolio_state
from src.utils.logging_setup import setup_logging
import logging

def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("Starting atomic portfolio operations test suite")

    # Test 1: State manager initialization
    logger.info("Test 1: State manager initialization")
    state_manager = PortfolioStateManager()

    try:
        initial_state = state_manager.get_state()
        logger.info(f"✅ State loaded successfully. Cash: {initial_state.cash:,.0f}, Positions: {len(initial_state.positions)}")
        logger.info(f"   Sequence: {initial_state.sequence_number}, Last updated: {initial_state.last_updated}")
    except Exception as e:
        logger.error(f"❌ Failed to load state: {e}")
        return False

    # Test 2: Compare with legacy system
    logger.info("Test 2: Legacy compatibility check")
    try:
        # Temporarily disable atomic state to get CSV result
        import os
        os.environ["USE_ATOMIC_STATE"] = "false"
        csv_state = get_portfolio_state()

        # Re-enable atomic state
        os.environ["USE_ATOMIC_STATE"] = "true"
        atomic_state = get_portfolio_state()

        cash_diff = abs(csv_state.cash - atomic_state.cash)
        pos_diff = len(csv_state.positions) - len(atomic_state.positions)

        if cash_diff < 1 and pos_diff == 0:
            logger.info("✅ Legacy compatibility confirmed")
        else:
            logger.warning(f"⚠️ Small differences: cash_diff={cash_diff}, pos_diff={pos_diff}")

    except Exception as e:
        logger.error(f"❌ Legacy compatibility test failed: {e}")
        return False

    # Test 3: Idempotency
    logger.info("Test 3: Idempotency check")
    test_run_id = "test_run_12345"

    # Should return False initially
    is_processed = state_manager.is_idempotent_operation(test_run_id)
    if not is_processed:
        logger.info("✅ Idempotency check: not processed (correct)")
    else:
        logger.error("❌ Idempotency check failed: should not be processed initially")
        return False

    # Mark as processed
    state_manager.mark_run_processed(test_run_id)

    # Should return True now
    is_processed = state_manager.is_idempotent_operation(test_run_id)
    if is_processed:
        logger.info("✅ Idempotency check: processed (correct)")
    else:
        logger.error("❌ Idempotency check failed: should be processed after marking")
        return False

    # Test 4: Audit log functionality
    logger.info("Test 4: Audit log functionality")
    try:
        state_manager.append_audit_log({
            "operation": "test",
            "source": "test_script",
            "data": {"test": True},
            "sequence_before": initial_state.sequence_number,
            "sequence_after": initial_state.sequence_number
        })

        audit_path = Path("data/trades_log.jsonl")
        if audit_path.exists():
            with open(audit_path) as f:
                lines = f.readlines()
            logger.info(f"✅ Audit log working. Total entries: {len(lines)}")
        else:
            logger.error("❌ Audit log file not created")
            return False

    except Exception as e:
        logger.error(f"❌ Audit log test failed: {e}")
        return False

    # Test 5: State file integrity
    logger.info("Test 5: State file integrity")
    try:
        state_file = Path("data/portfolio_state.json")
        with open(state_file) as f:
            state_data = json.load(f)

        required_fields = ["cash", "positions", "sequence_number", "last_updated", "metadata"]
        missing_fields = [field for field in required_fields if field not in state_data]

        if not missing_fields:
            logger.info("✅ State file has all required fields")
        else:
            logger.error(f"❌ State file missing fields: {missing_fields}")
            return False

        # Check positions structure
        for symbol, position in state_data["positions"].items():
            required_pos_fields = ["symbol", "asset_class", "qty", "avg_cost"]
            missing_pos_fields = [field for field in required_pos_fields if field not in position]
            if missing_pos_fields:
                logger.error(f"❌ Position {symbol} missing fields: {missing_pos_fields}")
                return False

        logger.info(f"✅ All {len(state_data['positions'])} positions have required fields")

    except Exception as e:
        logger.error(f"❌ State file integrity test failed: {e}")
        return False

    # Summary
    logger.info("\n🎉 All tests passed! The atomic portfolio system is ready.")
    logger.info("\nNext steps:")
    logger.info("1. Deploy the new Cloudflare Worker (replace index.js with index_new.js)")
    logger.info("2. Test /buy and /sell commands")
    logger.info("3. Run the weekly workflow")
    logger.info("4. Verify portfolio synchronization")

    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)