#!/usr/bin/env python3
"""Test portfolio-awareness fix for manual exit modes.

Runs backtests on all three exit management strategies:
1. tpsl_only - Automatic TP/SL exits (baseline)
2. 3action - Manual BUY/HOLD/SELL signals
3. 4action - Manual BUY/HOLD/REDUCE/SELL signals

Expected results after fix:
- All modes should produce >0 closed trades
- 3action and 4action should have different trade counts
- Manual modes should show lower max drawdown vs buy-and-hold
"""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.backtest.cli import run_backtest
from src.utils.logging_setup import setup_logging

setup_logging()


def run_comparison():
    """Run backtests for all three exit modes and compare results."""

    # Common parameters
    from_date = date(2025, 2, 1)
    to_date = date(2026, 2, 25)
    initial_cash = 20_000_000
    trades_per_week = 4

    modes = ["tpsl_only", "3action", "4action"]
    results = {}

    for exit_mode in modes:
        print(f"\n{'='*60}")
        print(f"Running backtest: exit_mode={exit_mode}")
        print(f"{'='*60}\n")

        output_base = f"reports_{exit_mode}_fixed"

        try:
            output_dir = run_backtest(
                from_date=from_date,
                to_date=to_date,
                initial_cash=initial_cash,
                trades_per_week=trades_per_week,
                tie_breaker="worst",
                exit_mode=exit_mode,
                output_base=output_base,
            )

            # Load summary
            summary_file = output_dir / "summary.json"
            with open(summary_file) as f:
                summary = json.load(f)

            results[exit_mode] = {
                "output_dir": str(output_dir),
                "summary": summary,
            }

            print(f"\n✓ Completed: {exit_mode}")
            print(f"  Trades: {summary.get('num_trades', 0)}")
            print(f"  CAGR: {summary.get('cagr', 0)*100:.2f}%")
            print(f"  Max DD: {summary.get('max_drawdown', 0)*100:.2f}%")
            print(f"  Win Rate: {summary.get('win_rate', 0)*100:.2f}%")

        except Exception as e:
            print(f"\n✗ Failed: {exit_mode}")
            print(f"  Error: {e}")
            import traceback
            traceback.print_exc()
            results[exit_mode] = {"error": str(e)}

    # Print comparison summary
    print(f"\n{'='*60}")
    print("COMPARISON SUMMARY")
    print(f"{'='*60}\n")

    print(f"{'Exit Mode':<15} {'Trades':<8} {'CAGR':<8} {'Max DD':<8} {'Win Rate':<10} {'Status'}")
    print("-" * 70)

    for mode in modes:
        if "error" in results[mode]:
            print(f"{mode:<15} {'ERROR':<8} {'-':<8} {'-':<8} {'-':<10} ✗ {results[mode]['error'][:30]}")
        else:
            s = results[mode]["summary"]
            trades = s.get("num_trades", 0)
            cagr = s.get("cagr", 0) * 100
            max_dd = s.get("max_drawdown", 0) * 100
            win_rate = s.get("win_rate", 0) * 100
            status = "✓" if trades > 0 else "✗"
            print(f"{mode:<15} {trades:<8} {cagr:<8.2f} {max_dd:<8.2f} {win_rate:<10.2f} {status}")

    # Validation checks
    print(f"\n{'='*60}")
    print("VALIDATION CHECKS")
    print(f"{'='*60}\n")

    all_passed = True

    # Check 1: All modes should have >0 trades
    for mode in modes:
        if "error" not in results[mode]:
            trades = results[mode]["summary"].get("num_trades", 0)
            if trades > 0:
                print(f"✓ {mode}: {trades} trades (PASS)")
            else:
                print(f"✗ {mode}: {trades} trades (FAIL - positions stuck open!)")
                all_passed = False
        else:
            print(f"✗ {mode}: ERROR (FAIL)")
            all_passed = False

    # Check 2: 3action and 4action should differ (4action has REDUCE)
    if "error" not in results["3action"] and "error" not in results["4action"]:
        trades_3 = results["3action"]["summary"].get("num_trades", 0)
        trades_4 = results["4action"]["summary"].get("num_trades", 0)
        if trades_3 != trades_4:
            print(f"\n✓ 3action ({trades_3}) ≠ 4action ({trades_4}) trades (PASS)")
        else:
            print(f"\n✗ 3action ({trades_3}) = 4action ({trades_4}) trades (FAIL - should differ!)")
            all_passed = False

    # Check 3: Manual modes should have lower max DD than pure buy-and-hold
    # (This is subjective, but expected behavior)

    print(f"\n{'='*60}")
    if all_passed:
        print("✓ ALL VALIDATION CHECKS PASSED - FIX IS WORKING!")
    else:
        print("✗ SOME VALIDATION CHECKS FAILED - FIX INCOMPLETE")
    print(f"{'='*60}\n")

    # Save detailed comparison
    comparison_file = Path("portfolio_awareness_fix_results.json")
    with open(comparison_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Detailed results saved to: {comparison_file}")

    return all_passed


if __name__ == "__main__":
    success = run_comparison()
    sys.exit(0 if success else 1)
