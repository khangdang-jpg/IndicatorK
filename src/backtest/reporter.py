"""Write backtest outputs to a timestamped reports/ folder.

Always produces exactly these files:
  summary.json           — all metrics in one file (see structure below)
  equity_curve[_label].csv
  trades[_label].csv

summary.json structure
──────────────────────
Single run (--tie-breaker worst|best):
  {
    "tie_breaker": "worst",
    "from_date": "2025-05-01", "to_date": "2026-02-25",
    "initial_cash": 10000000, "final_value": ...,
    "cagr": ..., "max_drawdown": ..., "win_rate": ...,
    "avg_hold_days": ..., "num_trades": ..., "profit_factor": ...
  }

Range run (--run-range):
  {
    "worst": { "tie_breaker": "worst", ...same fields },
    "best":  { "tie_breaker": "best",  ...same fields },
    "best_minus_worst": { "cagr": ..., "max_drawdown": ..., ... }
  }
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from pathlib import Path

from src.backtest.engine import ClosedTrade

logger = logging.getLogger(__name__)

_NUMERIC_DIFF_KEYS = [
    "final_value",
    "cagr",
    "max_drawdown",
    "win_rate",
    "avg_hold_days",
    "num_trades",
    "profit_factor",
    "avg_invested_pct",
]


def make_output_dir(base_dir: str = "reports") -> Path:
    """Create and return a unique timestamped subdirectory under *base_dir*."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(base_dir) / ts
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Report directory: %s", output_dir)
    return output_dir


# ---------------------------------------------------------------------------
# Summary — always ONE file
# ---------------------------------------------------------------------------

def write_summary(output_dir: Path, data: dict) -> None:
    """Write summary.json.

    *data* is either a flat metrics dict (single run) or a
    {worst, best, best_minus_worst} dict (range run).
    """
    path = output_dir / "summary.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    logger.info("Wrote %s", path)


def build_range_summary(worst: dict, best: dict) -> dict:
    """Return the nested summary payload for a --run-range backtest."""
    diff: dict = {}
    for k in _NUMERIC_DIFF_KEYS:
        w = worst.get(k)
        b = best.get(k)
        if isinstance(w, (int, float)) and isinstance(b, (int, float)):
            diff[k] = round(b - w, 4)
        else:
            diff[k] = None
    return {"worst": worst, "best": best, "best_minus_worst": diff}


# ---------------------------------------------------------------------------
# Equity curve  (one per scenario when --run-range)
# ---------------------------------------------------------------------------

def write_equity_curve(
    output_dir: Path,
    equity_curve: list[dict],
    label: str = "",
) -> None:
    fname = f"equity_curve_{label}.csv" if label else "equity_curve.csv"
    path = output_dir / fname
    fieldnames = ["date", "total_value", "cash", "open_positions_value"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(equity_curve)
    logger.info("Wrote %s (%d rows)", path, len(equity_curve))


# ---------------------------------------------------------------------------
# Trades  (one per scenario when --run-range)
# ---------------------------------------------------------------------------

def write_trades(
    output_dir: Path,
    closed_trades: list[ClosedTrade],
    label: str = "",
) -> None:
    fname = f"trades_{label}.csv" if label else "trades.csv"
    path = output_dir / fname
    fieldnames = [
        "symbol",
        "entry_date",
        "entry_price",
        "exit_date",
        "exit_price",
        "reason",
        "return_pct",
        "pnl_vnd",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for t in closed_trades:
            writer.writerow(
                {
                    "symbol": t.symbol,
                    "entry_date": t.entry_date.isoformat(),
                    "entry_price": t.entry_price,
                    "exit_date": t.exit_date.isoformat(),
                    "exit_price": t.exit_price,
                    "reason": t.reason,
                    "return_pct": t.return_pct,
                    "pnl_vnd": t.pnl_vnd,
                }
            )
    logger.info("Wrote %s (%d trades)", path, len(closed_trades))
