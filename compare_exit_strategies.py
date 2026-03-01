#!/usr/bin/env python3
"""Compare the three exit strategies: tpsl_only, 3action, and 4action."""

import sys
from datetime import date
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).resolve().parent))

from src.backtest.cli import run_backtest
from src.utils.logging_setup import setup_logging

def main():
    setup_logging()

    # Test parameters - 1 year backtest
    from_date = date(2025, 3, 1)  # Start from March 2025
    to_date = date(2026, 3, 1)    # End at March 2026
    initial_cash = 20_000_000     # 20M VND

    exit_strategies = {
        "tpsl_only": "Automatic TP/SL exits only (current implementation)",
        "3action": "BUY/HOLD/SELL signals - manual exits on SELL",
        "4action": "BUY/HOLD/REDUCE/SELL signals - manual exits on REDUCE (50%) and SELL"
    }

    results = {}

    print("🔄 Running backtests for all three exit strategies...")
    print(f"📅 Period: {from_date} to {to_date}")
    print(f"💰 Initial cash: {initial_cash:,} VND")
    print()

    for exit_mode, description in exit_strategies.items():
        print(f"▶️  Running {exit_mode}: {description}")

        try:
            output_dir = run_backtest(
                from_date=from_date,
                to_date=to_date,
                initial_cash=initial_cash,
                trades_per_week=4,
                universe="data/watchlist.txt",
                tie_breaker="worst",  # Conservative approach
                exit_mode=exit_mode,
                mode="generate",
                run_range=False,
                output_base=f"reports_{exit_mode}",
            )

            # Read the summary
            summary_file = output_dir / "summary.json"
            if summary_file.exists():
                import json
                with open(summary_file) as f:
                    summary = json.load(f)
                results[exit_mode] = {
                    "summary": summary,
                    "output_dir": str(output_dir),
                    "description": description
                }
                print(f"✅ Completed {exit_mode} - CAGR: {summary.get('cagr', 0) * 100:.2f}%")
            else:
                print(f"❌ No summary found for {exit_mode}")

        except Exception as e:
            print(f"❌ Failed {exit_mode}: {e}")

        print()

    # Compare results
    if len(results) >= 2:
        print("📊 COMPARISON RESULTS")
        print("=" * 80)

        print(f"{'Strategy':<12} {'CAGR':<8} {'Sharpe':<8} {'Win Rate':<10} {'Max DD':<10} {'Trades':<8} {'Avg Hold':<10}")
        print("-" * 80)

        for exit_mode, data in results.items():
            summary = data["summary"]
            cagr = summary.get('cagr', 0) * 100
            sharpe = _calculate_sharpe_ratio(summary)
            win_rate = summary.get('win_rate', 0) * 100
            max_dd = summary.get('max_drawdown', 0) * 100
            trades = summary.get('num_trades', 0)
            avg_hold = summary.get('avg_hold_days', 0)

            print(f"{exit_mode:<12} {cagr:>6.2f}% {sharpe:>6.2f} {win_rate:>8.1f}% {max_dd:>8.2f}% {trades:>6} {avg_hold:>8.1f}d")

        print()
        print("📈 DETAILED ANALYSIS")
        print("=" * 80)

        best_cagr = max(results.items(), key=lambda x: x[1]["summary"].get("cagr", 0))
        best_sharpe = max(results.items(), key=lambda x: _calculate_sharpe_ratio(x[1]["summary"]))
        lowest_dd = min(results.items(), key=lambda x: x[1]["summary"].get("max_drawdown", 1))

        print(f"🏆 Best CAGR: {best_cagr[0]} ({best_cagr[1]['summary'].get('cagr', 0) * 100:.2f}%)")
        print(f"⚖️  Best Sharpe: {best_sharpe[0]} ({_calculate_sharpe_ratio(best_sharpe[1]['summary']):.2f})")
        print(f"🛡️  Lowest Max DD: {lowest_dd[0]} ({lowest_dd[1]['summary'].get('max_drawdown', 0) * 100:.2f}%)")

        print()
        print("📁 Output directories:")
        for exit_mode, data in results.items():
            print(f"  {exit_mode}: {data['output_dir']}")

def _calculate_sharpe_ratio(summary):
    """Calculate Sharpe ratio approximation from CAGR and max drawdown."""
    cagr = summary.get('cagr', 0)
    max_dd = summary.get('max_drawdown', 0.01)  # Avoid division by zero

    # Simple approximation: return/risk ratio
    # Not exact Sharpe but gives relative comparison
    if max_dd > 0:
        return cagr / max_dd
    return 0

if __name__ == "__main__":
    main()