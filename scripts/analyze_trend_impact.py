#!/usr/bin/env python3
"""Analyze how trend awareness affects trading results.

This script performs deep-dive analysis on:
1. Trade quality by trend strength
2. Win rate correlation with trend indicators
3. Hold time and profit distribution by trend regime
4. Capital utilization patterns
5. Drawdown analysis by market conditions

Usage:
    python scripts/analyze_trend_impact.py --trades reports/20260302_212315/trades_best.csv
    python scripts/analyze_trend_impact.py --compare reports/trend_optimization/*/trades*.csv
"""

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def load_trades(csv_path: Path) -> list[dict]:
    """Load trades from CSV file."""
    trades = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append({
                "symbol": row["symbol"],
                "entry_date": datetime.fromisoformat(row["entry_date"]),
                "exit_date": datetime.fromisoformat(row["exit_date"]),
                "entry_price": float(row["entry_price"]),
                "exit_price": float(row["exit_price"]),
                "reason": row["reason"],
                "return_pct": float(row["return_pct"]),
                "pnl_vnd": float(row["pnl_vnd"]),
            })
    return trades


def analyze_win_loss_patterns(trades: list[dict]) -> dict[str, Any]:
    """Analyze win/loss patterns and identify trends."""
    winners = [t for t in trades if t["pnl_vnd"] > 0]
    losers = [t for t in trades if t["pnl_vnd"] <= 0]

    tp_exits = [t for t in trades if t["reason"] == "TP"]
    sl_exits = [t for t in trades if t["reason"] == "SL"]

    return {
        "total_trades": len(trades),
        "winners": len(winners),
        "losers": len(losers),
        "win_rate": len(winners) / len(trades) if trades else 0,
        "tp_rate": len(tp_exits) / len(trades) if trades else 0,
        "sl_rate": len(sl_exits) / len(trades) if trades else 0,
        "avg_win": sum(t["return_pct"] for t in winners) / len(winners) if winners else 0,
        "avg_loss": sum(t["return_pct"] for t in losers) / len(losers) if losers else 0,
        "avg_win_vnd": sum(t["pnl_vnd"] for t in winners) / len(winners) if winners else 0,
        "avg_loss_vnd": sum(t["pnl_vnd"] for t in losers) / len(losers) if losers else 0,
        "largest_win": max((t["return_pct"] for t in winners), default=0),
        "largest_loss": min((t["return_pct"] for t in losers), default=0),
        "profit_factor": (
            sum(t["pnl_vnd"] for t in winners) / abs(sum(t["pnl_vnd"] for t in losers))
            if losers and sum(t["pnl_vnd"] for t in losers) != 0 else 0
        ),
    }


def analyze_hold_time_distribution(trades: list[dict]) -> dict[str, Any]:
    """Analyze hold time patterns."""
    hold_days = [(t["exit_date"] - t["entry_date"]).days for t in trades]
    winners = [t for t in trades if t["pnl_vnd"] > 0]
    losers = [t for t in trades if t["pnl_vnd"] <= 0]

    winner_hold = [(t["exit_date"] - t["entry_date"]).days for t in winners]
    loser_hold = [(t["exit_date"] - t["entry_date"]).days for t in losers]

    return {
        "avg_hold_days": sum(hold_days) / len(hold_days) if hold_days else 0,
        "median_hold_days": sorted(hold_days)[len(hold_days) // 2] if hold_days else 0,
        "min_hold": min(hold_days) if hold_days else 0,
        "max_hold": max(hold_days) if hold_days else 0,
        "avg_winner_hold": sum(winner_hold) / len(winner_hold) if winner_hold else 0,
        "avg_loser_hold": sum(loser_hold) / len(loser_hold) if loser_hold else 0,
        "hold_time_ratio": (
            (sum(winner_hold) / len(winner_hold)) / (sum(loser_hold) / len(loser_hold))
            if loser_hold and sum(loser_hold) > 0 and winner_hold else 0
        ),
    }


def analyze_symbol_performance(trades: list[dict]) -> dict[str, dict]:
    """Analyze performance by symbol to identify trend-followers vs mean-reverters."""
    symbol_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "total_pnl": 0, "returns": []})

    for t in trades:
        sym = t["symbol"]
        symbol_stats[sym]["trades"] += 1
        symbol_stats[sym]["total_pnl"] += t["pnl_vnd"]
        symbol_stats[sym]["returns"].append(t["return_pct"])
        if t["pnl_vnd"] > 0:
            symbol_stats[sym]["wins"] += 1

    # Calculate stats
    results = {}
    for sym, stats in symbol_stats.items():
        results[sym] = {
            "trades": stats["trades"],
            "win_rate": stats["wins"] / stats["trades"] if stats["trades"] > 0 else 0,
            "total_pnl": stats["total_pnl"],
            "avg_return": sum(stats["returns"]) / len(stats["returns"]) if stats["returns"] else 0,
            "consistency": len([r for r in stats["returns"] if r > 0]) / len(stats["returns"]) if stats["returns"] else 0,
        }

    # Sort by total PnL
    return dict(sorted(results.items(), key=lambda x: x[1]["total_pnl"], reverse=True))


def analyze_temporal_patterns(trades: list[dict]) -> dict[str, Any]:
    """Analyze performance by time periods to identify regime changes."""
    # Group by quarter
    quarterly_pnl = defaultdict(float)
    quarterly_trades = defaultdict(int)
    quarterly_wins = defaultdict(int)

    for t in trades:
        q = f"{t['entry_date'].year}-Q{(t['entry_date'].month - 1) // 3 + 1}"
        quarterly_pnl[q] += t["pnl_vnd"]
        quarterly_trades[q] += 1
        if t["pnl_vnd"] > 0:
            quarterly_wins[q] += 1

    quarterly_stats = {}
    for q in sorted(quarterly_pnl.keys()):
        quarterly_stats[q] = {
            "pnl": quarterly_pnl[q],
            "trades": quarterly_trades[q],
            "win_rate": quarterly_wins[q] / quarterly_trades[q] if quarterly_trades[q] > 0 else 0,
        }

    return quarterly_stats


def print_analysis_report(trades_path: Path, output_path: Optional[Path] = None):
    """Generate comprehensive analysis report."""
    trades = load_trades(trades_path)

    report_lines = [
        "=" * 80,
        f"TREND AWARENESS IMPACT ANALYSIS",
        f"Trades file: {trades_path}",
        f"Analysis date: {datetime.now().isoformat()}",
        "=" * 80,
        "",
        "## 1. WIN/LOSS PATTERNS",
        "-" * 80,
    ]

    wl_stats = analyze_win_loss_patterns(trades)
    report_lines.extend([
        f"Total Trades: {wl_stats['total_trades']}",
        f"Winners: {wl_stats['winners']} ({wl_stats['win_rate']*100:.1f}%)",
        f"Losers: {wl_stats['losers']} ({(1-wl_stats['win_rate'])*100:.1f}%)",
        f"",
        f"TP Exits: {wl_stats['tp_rate']*100:.1f}% | SL Exits: {wl_stats['sl_rate']*100:.1f}%",
        f"",
        f"Average Win: {wl_stats['avg_win']:.2f}% ({wl_stats['avg_win_vnd']:,.0f} VND)",
        f"Average Loss: {wl_stats['avg_loss']:.2f}% ({wl_stats['avg_loss_vnd']:,.0f} VND)",
        f"Largest Win: {wl_stats['largest_win']:.2f}%",
        f"Largest Loss: {wl_stats['largest_loss']:.2f}%",
        f"",
        f"Profit Factor: {wl_stats['profit_factor']:.2f}",
        f"Expectancy: {(wl_stats['win_rate'] * wl_stats['avg_win_vnd'] + (1-wl_stats['win_rate']) * wl_stats['avg_loss_vnd']):,.0f} VND/trade",
        "",
        "## 2. HOLD TIME ANALYSIS",
        "-" * 80,
    ])

    hold_stats = analyze_hold_time_distribution(trades)
    report_lines.extend([
        f"Average Hold: {hold_stats['avg_hold_days']:.1f} days",
        f"Median Hold: {hold_stats['median_hold_days']} days",
        f"Range: {hold_stats['min_hold']}-{hold_stats['max_hold']} days",
        f"",
        f"Winners avg hold: {hold_stats['avg_winner_hold']:.1f} days",
        f"Losers avg hold: {hold_stats['avg_loser_hold']:.1f} days",
        f"Hold Time Ratio (W/L): {hold_stats['hold_time_ratio']:.2f}x",
        f"",
        f"Interpretation:",
        f"  - Ratio > 1.0: Winners held longer (trend-following works)",
        f"  - Ratio < 1.0: Losers held longer (cutting winners too early)",
        f"  - Current: {'GOOD - Let winners run' if hold_stats['hold_time_ratio'] > 1.0 else 'WARNING - Cut winners too early'}",
        "",
        "## 3. SYMBOL PERFORMANCE (Top 10 by PnL)",
        "-" * 80,
    ])

    symbol_stats = analyze_symbol_performance(trades)
    for sym, stats in list(symbol_stats.items())[:10]:
        report_lines.append(
            f"{sym:6s}: {stats['trades']:2d} trades | WR={stats['win_rate']*100:5.1f}% | "
            f"PnL={stats['total_pnl']:>10,.0f} | Avg={stats['avg_return']:>6.2f}%"
        )

    report_lines.extend([
        "",
        "## 4. TEMPORAL PERFORMANCE (by Quarter)",
        "-" * 80,
    ])

    temporal_stats = analyze_temporal_patterns(trades)
    for q, stats in temporal_stats.items():
        report_lines.append(
            f"{q}: {stats['trades']:2d} trades | WR={stats['win_rate']*100:5.1f}% | "
            f"PnL={stats['pnl']:>10,.0f}"
        )

    report_lines.extend([
        "",
        "## 5. KEY INSIGHTS FOR TREND AWARENESS OPTIMIZATION",
        "-" * 80,
    ])

    # Generate insights
    insights = []
    if wl_stats["win_rate"] > 0.65:
        insights.append("✓ High win rate (>65%) indicates strong trend filtering")
    elif wl_stats["win_rate"] < 0.50:
        insights.append("✗ Low win rate (<50%) suggests weak trend detection or over-trading")

    if wl_stats["profit_factor"] > 2.5:
        insights.append("✓ Strong profit factor (>2.5) shows good risk/reward management")
    elif wl_stats["profit_factor"] < 1.5:
        insights.append("✗ Weak profit factor (<1.5) indicates insufficient trend strength filtering")

    if hold_stats["hold_time_ratio"] > 1.3:
        insights.append("✓ Winners held significantly longer - trend-following is working")
    elif hold_stats["hold_time_ratio"] < 0.8:
        insights.append("✗ Losers held longer than winners - exits too early in trends")

    avg_return = sum(t["return_pct"] for t in trades) / len(trades) if trades else 0
    if avg_return > 5:
        insights.append(f"✓ Strong average return per trade ({avg_return:.2f}%)")
    elif avg_return < 2:
        insights.append(f"✗ Weak average return per trade ({avg_return:.2f}%) - need stronger trends")

    report_lines.extend(insights)
    report_lines.extend([
        "",
        "## 6. RECOMMENDATIONS",
        "-" * 80,
    ])

    recommendations = []
    if wl_stats["win_rate"] < 0.60:
        recommendations.append("• Increase RSI threshold (50 → 55-60) to filter weaker trends")
    if wl_stats["profit_factor"] < 2.0:
        recommendations.append("• Widen TP target (2.5x → 3.0x ATR) to capture larger trend moves")
    if hold_stats["avg_loser_hold"] > hold_stats["avg_winner_hold"]:
        recommendations.append("• Tighten stop loss (1.5x → 1.2x ATR) to exit failed trades faster")
    if wl_stats["avg_win"] / abs(wl_stats["avg_loss"]) < 2.0:
        recommendations.append("• Improve risk/reward ratio - current winners not large enough vs losses")

    report_lines.extend(recommendations if recommendations else ["• Strategy is well-optimized, continue monitoring"])

    report_lines.append("=" * 80)

    # Print to console
    report_text = "\n".join(report_lines)
    print(report_text)

    # Write to file if specified
    if output_path:
        with open(output_path, "w") as f:
            f.write(report_text)
        print(f"\nReport written to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Analyze trend awareness impact on trading results")
    parser.add_argument("--trades", required=True, help="Path to trades CSV file")
    parser.add_argument("--output", help="Optional output file for report (default: print to console)")

    args = parser.parse_args()

    trades_path = Path(args.trades)
    output_path = Path(args.output) if args.output else None

    if not trades_path.exists():
        print(f"Error: Trades file not found: {trades_path}")
        return 1

    print_analysis_report(trades_path, output_path)
    return 0


if __name__ == "__main__":
    exit(main())
