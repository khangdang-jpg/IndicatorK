#!/usr/bin/env python3
"""Trend Awareness Optimization Suite.

Tests multiple trend detection and capital allocation strategies:
1. RSI threshold optimization (grid search)
2. Trend strength scoring system
3. Volume-weighted trend confirmation
4. Dynamic position sizing based on trend strength

Run:
    python scripts/optimize_trend_awareness.py --test all
    python scripts/optimize_trend_awareness.py --test rsi-sweep
    python scripts/optimize_trend_awareness.py --test trend-scoring
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from src.backtest.cli import run_backtest
from src.utils.config import get_provider, get_risk_config, get_strategy, load_watchlist

logger = logging.getLogger(__name__)


def run_rsi_sweep(
    from_date: date,
    to_date: date,
    initial_cash: int,
    universe: str,
    output_base: str,
) -> dict[str, Any]:
    """Test RSI threshold grid: 40, 45, 50, 55, 60, 65.

    Returns summary metrics for each RSI threshold.
    """
    rsi_thresholds = [40, 45, 50, 55, 60, 65]
    results = {}

    logger.info("=" * 80)
    logger.info("HYPOTHESIS 3: RSI Threshold Optimization")
    logger.info("Testing thresholds: %s", rsi_thresholds)
    logger.info("=" * 80)

    for rsi_min in rsi_thresholds:
        logger.info("\n" + "-" * 80)
        logger.info("Testing RSI breakout min: %d", rsi_min)
        logger.info("-" * 80)

        # Override strategy parameters
        from src.strategies.trend_momentum_atr import TrendMomentumATRStrategy
        strategy = TrendMomentumATRStrategy(params={
            "ma_short": 10,
            "ma_long": 30,
            "rsi_period": 14,
            "atr_period": 14,
            "atr_stop_mult": 1.5,
            "atr_target_mult": 2.5,
            "rsi_breakout_min": float(rsi_min),  # TEST VARIABLE
            "entry_buffer_pct": 0.001,
            "price_tick": 10,
        })

        output_dir = run_backtest(
            from_date=from_date,
            to_date=to_date,
            initial_cash=initial_cash,
            trades_per_week=4,
            universe=universe,
            tie_breaker="worst",
            exit_mode="tpsl_only",
            mode="generate",
            run_range=False,
            output_base=f"{output_base}/rsi_{rsi_min}",
            strategy=strategy,
        )

        # Load summary
        summary_path = output_dir / "summary.json"
        with open(summary_path, "r") as f:
            summary = json.load(f)

        results[f"rsi_{rsi_min}"] = summary

        logger.info("Results for RSI=%d:", rsi_min)
        logger.info("  CAGR: %.2f%%", summary["cagr"] * 100)
        logger.info("  Max DD: %.2f%%", summary["max_drawdown"] * 100)
        logger.info("  Win Rate: %.2f%%", summary["win_rate"] * 100)
        logger.info("  Trades: %d", summary["num_trades"])
        logger.info("  Profit Factor: %.2f", summary["profit_factor"] or 0)
        logger.info("  Avg Invested: %.2f%%", summary["avg_invested_pct"] * 100)

        # Calculate Sharpe approximation
        sharpe_approx = summary["cagr"] / summary["max_drawdown"] if summary["max_drawdown"] > 0 else 0
        logger.info("  Sharpe (approx): %.2f", sharpe_approx)

    return results


def run_volume_confirmation_test(
    from_date: date,
    to_date: date,
    initial_cash: int,
    universe: str,
    output_base: str,
) -> dict[str, Any]:
    """Test volume confirmation thresholds: 1.0x, 1.2x, 1.5x avg volume.

    Requires modifying strategy to include volume filters.
    NOTE: This is a placeholder - full implementation requires strategy modification.
    """
    logger.info("=" * 80)
    logger.info("HYPOTHESIS 2: Volume-Weighted Trend Confirmation")
    logger.info("NOTE: Requires strategy modification - running baseline for comparison")
    logger.info("=" * 80)

    # For now, just run baseline
    from src.strategies.trend_momentum_atr import TrendMomentumATRStrategy
    strategy = TrendMomentumATRStrategy()

    output_dir = run_backtest(
        from_date=from_date,
        to_date=to_date,
        initial_cash=initial_cash,
        trades_per_week=4,
        universe=universe,
        tie_breaker="worst",
        exit_mode="tpsl_only",
        mode="generate",
        run_range=False,
        output_base=f"{output_base}/volume_baseline",
        strategy=strategy,
    )

    summary_path = output_dir / "summary.json"
    with open(summary_path, "r") as f:
        summary = json.load(f)

    logger.info("Baseline results (volume confirmation already in strategy):")
    logger.info("  CAGR: %.2f%%", summary["cagr"] * 100)
    logger.info("  See strategy line 132: vol_ok = volumes[-1] >= vol_avg")

    return {"volume_baseline": summary}


def run_position_sizing_test(
    from_date: date,
    to_date: date,
    initial_cash: int,
    universe: str,
    output_base: str,
) -> dict[str, Any]:
    """Test different position sizing approaches.

    Current: risk-based (1% risk per trade)
    Test: fixed allocations of 8%, 10%, 12%, 15% per position
    """
    position_sizes = [0.08, 0.10, 0.12, 0.15]
    results = {}

    logger.info("=" * 80)
    logger.info("HYPOTHESIS 4: Position Sizing Optimization (Capital Utilization)")
    logger.info("Testing fixed allocation %: %s", [f"{p*100:.0f}%" for p in position_sizes])
    logger.info("=" * 80)

    for pct in position_sizes:
        logger.info("\n" + "-" * 80)
        logger.info("Testing position size: %.0f%% per trade", pct * 100)
        logger.info("-" * 80)

        # Modify risk config to use fixed allocation
        risk_config = get_risk_config()
        risk_config["allocation"] = {
            "alloc_mode": "fixed_pct",
            "fixed_alloc_pct_per_trade": pct,
            "min_alloc_pct": 0.03,
            "max_alloc_pct": 0.20,
        }

        from src.strategies.trend_momentum_atr import TrendMomentumATRStrategy
        strategy = TrendMomentumATRStrategy()

        output_dir = run_backtest(
            from_date=from_date,
            to_date=to_date,
            initial_cash=initial_cash,
            trades_per_week=4,
            universe=universe,
            tie_breaker="worst",
            exit_mode="tpsl_only",
            mode="generate",
            run_range=False,
            output_base=f"{output_base}/position_{int(pct*100)}pct",
            strategy=strategy,
            risk_config=risk_config,
        )

        summary_path = output_dir / "summary.json"
        with open(summary_path, "r") as f:
            summary = json.load(f)

        results[f"pos_{int(pct*100)}pct"] = summary

        logger.info("Results for %d%% position size:", int(pct * 100))
        logger.info("  CAGR: %.2f%%", summary["cagr"] * 100)
        logger.info("  Max DD: %.2f%%", summary["max_drawdown"] * 100)
        logger.info("  Win Rate: %.2f%%", summary["win_rate"] * 100)
        logger.info("  Trades: %d", summary["num_trades"])
        logger.info("  Profit Factor: %.2f", summary["profit_factor"] or 0)
        logger.info("  Avg Invested: %.2f%%", summary["avg_invested_pct"] * 100)

        sharpe_approx = summary["cagr"] / summary["max_drawdown"] if summary["max_drawdown"] > 0 else 0
        calmar = summary["cagr"] / summary["max_drawdown"] if summary["max_drawdown"] > 0 else 0
        logger.info("  Sharpe (approx): %.2f", sharpe_approx)
        logger.info("  Calmar: %.2f", calmar)

    return results


def run_atr_multiplier_sweep(
    from_date: date,
    to_date: date,
    initial_cash: int,
    universe: str,
    output_base: str,
) -> dict[str, Any]:
    """Test different ATR stop/target multipliers.

    Current: 1.5x stop, 2.5x target (R:R = 1.67:1)
    Test grid:
    - Conservative: 1.2x/2.0x (R:R = 1.67:1)
    - Baseline: 1.5x/2.5x (R:R = 1.67:1)
    - Aggressive: 2.0x/3.5x (R:R = 1.75:1)
    """
    configs = [
        {"stop": 1.2, "target": 2.0, "label": "conservative"},
        {"stop": 1.5, "target": 2.5, "label": "baseline"},
        {"stop": 2.0, "target": 3.5, "label": "aggressive"},
    ]
    results = {}

    logger.info("=" * 80)
    logger.info("HYPOTHESIS 5: ATR Multiplier Optimization")
    logger.info("Testing stop/target combinations")
    logger.info("=" * 80)

    for cfg in configs:
        logger.info("\n" + "-" * 80)
        logger.info("Testing %s: stop=%.1fx, target=%.1fx", cfg["label"], cfg["stop"], cfg["target"])
        logger.info("-" * 80)

        from src.strategies.trend_momentum_atr import TrendMomentumATRStrategy
        strategy = TrendMomentumATRStrategy(params={
            "atr_stop_mult": cfg["stop"],
            "atr_target_mult": cfg["target"],
        })

        output_dir = run_backtest(
            from_date=from_date,
            to_date=to_date,
            initial_cash=initial_cash,
            trades_per_week=4,
            universe=universe,
            tie_breaker="worst",
            exit_mode="tpsl_only",
            mode="generate",
            run_range=False,
            output_base=f"{output_base}/atr_{cfg['label']}",
            strategy=strategy,
        )

        summary_path = output_dir / "summary.json"
        with open(summary_path, "r") as f:
            summary = json.load(f)

        results[cfg["label"]] = summary

        logger.info("Results for %s:", cfg["label"])
        logger.info("  CAGR: %.2f%%", summary["cagr"] * 100)
        logger.info("  Max DD: %.2f%%", summary["max_drawdown"] * 100)
        logger.info("  Win Rate: %.2f%%", summary["win_rate"] * 100)
        logger.info("  Avg Hold: %.1f days", summary["avg_hold_days"])
        logger.info("  Profit Factor: %.2f", summary["profit_factor"] or 0)

        sharpe_approx = summary["cagr"] / summary["max_drawdown"] if summary["max_drawdown"] > 0 else 0
        logger.info("  Sharpe (approx): %.2f", sharpe_approx)

    return results


def write_comparison_report(results: dict[str, dict], output_path: Path) -> None:
    """Write markdown comparison report for all tested configurations."""
    with open(output_path, "w") as f:
        f.write("# Trend Awareness Optimization Results\n\n")
        f.write(f"**Generated**: {date.today().isoformat()}\n\n")

        f.write("## Performance Summary\n\n")
        f.write("| Configuration | CAGR | Max DD | Sharpe* | Win Rate | Trades | PF | Avg Inv |\n")
        f.write("|--------------|------|--------|---------|----------|--------|----|---------|\n")

        for name, summary in results.items():
            cagr = summary["cagr"] * 100
            dd = summary["max_drawdown"] * 100
            sharpe = cagr / dd if dd > 0 else 0
            wr = summary["win_rate"] * 100
            trades = summary["num_trades"]
            pf = summary.get("profit_factor") or 0
            inv = summary["avg_invested_pct"] * 100

            f.write(f"| {name} | {cagr:.1f}% | {dd:.1f}% | {sharpe:.2f} | {wr:.1f}% | {trades} | {pf:.2f} | {inv:.1f}% |\n")

        f.write("\n*Sharpe approximated as CAGR/MaxDD\n\n")

        # Find best by different metrics
        f.write("## Best Configurations\n\n")

        best_sharpe = max(results.items(), key=lambda x: x[1]["cagr"] / x[1]["max_drawdown"] if x[1]["max_drawdown"] > 0 else 0)
        f.write(f"**Best Sharpe**: {best_sharpe[0]} (Sharpe={best_sharpe[1]['cagr']/best_sharpe[1]['max_drawdown']:.2f})\n\n")

        best_cagr = max(results.items(), key=lambda x: x[1]["cagr"])
        f.write(f"**Best CAGR**: {best_cagr[0]} (CAGR={best_cagr[1]['cagr']*100:.2f}%)\n\n")

        best_wr = max(results.items(), key=lambda x: x[1]["win_rate"])
        f.write(f"**Best Win Rate**: {best_wr[0]} (WR={best_wr[1]['win_rate']*100:.2f}%)\n\n")

        # Detailed results
        f.write("## Detailed Results\n\n")
        for name, summary in results.items():
            f.write(f"### {name}\n\n")
            f.write(f"- **CAGR**: {summary['cagr']*100:.2f}%\n")
            f.write(f"- **Max Drawdown**: {summary['max_drawdown']*100:.2f}%\n")
            f.write(f"- **Win Rate**: {summary['win_rate']*100:.2f}%\n")
            f.write(f"- **Num Trades**: {summary['num_trades']}\n")
            f.write(f"- **Profit Factor**: {summary.get('profit_factor', 0):.2f}\n")
            f.write(f"- **Avg Hold Days**: {summary['avg_hold_days']:.1f}\n")
            f.write(f"- **Avg Invested**: {summary['avg_invested_pct']*100:.2f}%\n")
            f.write(f"- **Sharpe (approx)**: {summary['cagr']/summary['max_drawdown']:.2f}\n")
            f.write(f"- **Calmar**: {summary['cagr']/summary['max_drawdown']:.2f}\n\n")


def main():
    parser = argparse.ArgumentParser(description="Optimize trend awareness parameters")
    parser.add_argument("--test", required=True,
                       choices=["all", "rsi-sweep", "volume", "position-size", "atr-sweep"],
                       help="Which optimization test to run")
    parser.add_argument("--from", dest="from_date", default="2022-01-01",
                       help="Backtest start date (default: 2022-01-01)")
    parser.add_argument("--to", dest="to_date", default="2025-04-01",
                       help="Backtest end date (default: 2025-04-01)")
    parser.add_argument("--initial-cash", type=int, default=20_000_000,
                       help="Initial capital (default: 20M VND)")
    parser.add_argument("--universe", default="data/watchlist.txt",
                       help="Watchlist file (default: data/watchlist.txt)")
    parser.add_argument("--output-base", default="reports/trend_optimization",
                       help="Output directory (default: reports/trend_optimization)")

    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date)
    to_date = date.fromisoformat(args.to_date)

    from src.utils.logging_setup import setup_logging
    setup_logging()

    all_results = {}

    if args.test == "all" or args.test == "rsi-sweep":
        rsi_results = run_rsi_sweep(
            from_date, to_date, args.initial_cash, args.universe, args.output_base
        )
        all_results.update(rsi_results)

    if args.test == "all" or args.test == "volume":
        vol_results = run_volume_confirmation_test(
            from_date, to_date, args.initial_cash, args.universe, args.output_base
        )
        all_results.update(vol_results)

    if args.test == "all" or args.test == "position-size":
        pos_results = run_position_sizing_test(
            from_date, to_date, args.initial_cash, args.universe, args.output_base
        )
        all_results.update(pos_results)

    if args.test == "all" or args.test == "atr-sweep":
        atr_results = run_atr_multiplier_sweep(
            from_date, to_date, args.initial_cash, args.universe, args.output_base
        )
        all_results.update(atr_results)

    # Write comparison report
    output_path = Path(args.output_base) / "OPTIMIZATION_RESULTS.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_comparison_report(all_results, output_path)

    logger.info("\n" + "=" * 80)
    logger.info("Optimization complete!")
    logger.info("Results written to: %s", output_path)
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
