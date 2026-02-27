#!/usr/bin/env python3
"""Parameter sweep for TrendMomentumATR: atr_stop_mult × atr_target_mult.

Fetches historical data ONCE, then runs all 16 combos in memory.

Usage:
    python scripts/sweep_params.py
    python scripts/sweep_params.py --from 2025-02-01 --to 2026-02-25
    python scripts/sweep_params.py --no-update   # print table only, don't write config
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

# Ensure project root is on sys.path so `src.*` imports resolve
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import OHLCV
from src.providers.base import PriceProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-memory provider — serves pre-fetched data for all sweep runs
# ---------------------------------------------------------------------------

class _PreloadedProvider(PriceProvider):
    """Wraps a pre-fetched dict[symbol → list[OHLCV]] for instant replay."""

    name = "preloaded"

    def __init__(self, data: dict[str, list[OHLCV]]) -> None:
        self._data = data

    def get_daily_history(self, symbol: str, start: date, end: date) -> list[OHLCV]:
        candles = self._data.get(symbol, [])
        return [c for c in candles if start <= c.date <= end]

    def get_last_prices(self, symbols: list[str]) -> dict[str, float]:
        result = {}
        for sym in symbols:
            candles = self._data.get(sym, [])
            if candles:
                result[sym] = candles[-1].close
        return result


# ---------------------------------------------------------------------------
# Sweep runner
# ---------------------------------------------------------------------------

ATR_STOP_MULTS  = [1.5, 1.8, 2.0, 2.2]
ATR_TARGET_MULTS = [1.4, 1.6, 1.8, 2.0]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="TrendMomentumATR parameter sweep")
    p.add_argument("--from", dest="from_date", default="2025-02-01")
    p.add_argument("--to",   dest="to_date",   default="2026-02-25")
    p.add_argument("--initial-cash", type=int,  default=20_000_000)
    p.add_argument("--trades-per-week", type=int, default=4)
    p.add_argument("--universe", default="data/watchlist.txt")
    p.add_argument("--no-update", action="store_true",
                   help="Print table only; do NOT update config/strategy.yml")
    return p.parse_args()


def _run_sweep(
    from_date: date,
    to_date: date,
    initial_cash: int,
    trades_per_week: int,
    universe: str,
) -> list[dict]:
    """Fetch data once, run all 16 combos, return list of result dicts."""
    from src.backtest.cli import _get_provider_with_fallback, _run_single
    from src.strategies.trend_momentum_atr import TrendMomentumATRStrategy
    from src.utils.config import get_risk_config, load_watchlist
    from src.utils.logging_setup import setup_logging

    setup_logging()

    risk_config = get_risk_config()
    symbols = load_watchlist(universe)

    # ------------------------------------------------------------------
    # Fetch all data once using the live provider
    # ------------------------------------------------------------------
    print(f"\nFetching data for {len(symbols)} symbols "
          f"({from_date - timedelta(weeks=52)} → {to_date}) …")
    live_provider = _get_provider_with_fallback()

    history_start = from_date - timedelta(weeks=52)
    all_data: dict[str, list[OHLCV]] = {}
    for sym in symbols:
        try:
            candles = live_provider.get_daily_history(sym, history_start, to_date)
        except Exception as exc:
            logger.warning("Failed to fetch %s: %s", sym, exc)
            candles = []
        if candles:
            all_data[sym] = sorted(candles, key=lambda c: c.date)
            print(f"  {sym}: {len(all_data[sym])} days")
        else:
            print(f"  {sym}: NO DATA")

    fetched_count = len(all_data)
    print(f"\nData fetched for {fetched_count}/{len(symbols)} symbols.")

    if fetched_count == 0:
        print("ERROR: no data fetched. Aborting sweep.")
        sys.exit(1)

    preloaded = _PreloadedProvider(all_data)

    # ------------------------------------------------------------------
    # Run all 16 combos
    # ------------------------------------------------------------------
    results = []
    total = len(ATR_STOP_MULTS) * len(ATR_TARGET_MULTS)
    run_idx = 0

    print(f"\nRunning {total} backtests ({from_date} → {to_date}) …\n")

    for stop_mult in ATR_STOP_MULTS:
        for target_mult in ATR_TARGET_MULTS:
            run_idx += 1
            label = f"stop={stop_mult:.1f}  target={target_mult:.1f}"
            print(f"  [{run_idx:2d}/{total}] {label} …", end=" ", flush=True)

            strategy = TrendMomentumATRStrategy(params={
                "ma_short": 10,
                "ma_long":  30,
                "rsi_period": 14,
                "atr_period": 14,
                "atr_stop_mult":   stop_mult,
                "atr_target_mult": target_mult,
            })

            engine = _run_single(
                from_date=from_date,
                to_date=to_date,
                initial_cash=initial_cash,
                order_size=None,
                trades_per_week=trades_per_week,
                mode="generate",
                plan_file="data/weekly_plan.json",
                tie_breaker="worst",
                provider=preloaded,
                strategy=strategy,
                risk_config=risk_config,
                symbols=symbols,
            )

            metrics = engine.compute_summary(from_date, to_date)
            metrics["atr_stop_mult"]   = stop_mult
            metrics["atr_target_mult"] = target_mult
            results.append(metrics)

            cagr_pct = metrics["cagr"] * 100
            dd_pct   = metrics["max_drawdown"] * 100
            pf       = metrics.get("profit_factor") or 0.0
            trades   = metrics["num_trades"]
            print(f"CAGR={cagr_pct:+6.1f}%  DD={dd_pct:5.1f}%  PF={pf:.2f}  n={trades}")

    return results


def _sort_key(r: dict) -> tuple:
    """Sort by CAGR desc, max_drawdown asc, profit_factor desc."""
    pf = r.get("profit_factor") or 0.0
    return (-r["cagr"], r["max_drawdown"], -pf)


def _print_table(results: list[dict]) -> None:
    header = (
        f"{'stop':>5}  {'target':>6}  {'CAGR':>8}  {'MaxDD':>6}  "
        f"{'PF':>5}  {'WR':>5}  {'n':>3}  {'AvgHold':>7}"
    )
    sep = "-" * len(header)
    print(f"\n{'RESULTS (sorted by CAGR desc, MaxDD asc, PF desc)':^{len(header)}}")
    print(sep)
    print(header)
    print(sep)
    for r in sorted(results, key=_sort_key):
        pf  = r.get("profit_factor") or 0.0
        print(
            f"{r['atr_stop_mult']:>5.1f}  {r['atr_target_mult']:>6.1f}  "
            f"{r['cagr']*100:>+7.1f}%  {r['max_drawdown']*100:>5.1f}%  "
            f"{pf:>5.2f}  {r['win_rate']*100:>4.0f}%  "
            f"{r['num_trades']:>3d}  {r['avg_hold_days']:>7.1f}d"
        )
    print(sep)


def _pick_best(results: list[dict]) -> dict:
    """Pick best tradeoff: CAGR >= 9% first; else highest CAGR with MaxDD <= 8%."""
    sorted_res = sorted(results, key=_sort_key)

    # Tier 1: CAGR >= 9%
    tier1 = [r for r in sorted_res if r["cagr"] >= 0.09]
    if tier1:
        return tier1[0]

    # Tier 2: MaxDD <= 8%
    tier2 = [r for r in sorted_res if r["max_drawdown"] <= 0.08]
    if tier2:
        return tier2[0]

    # Fallback: best overall by sort key
    return sorted_res[0]


def _update_strategy_config(stop_mult: float, target_mult: float) -> None:
    """Rewrite atr_stop_mult and atr_target_mult lines in config/strategy.yml."""
    import re

    config_path = Path(__file__).resolve().parent.parent / "config" / "strategy.yml"
    text = config_path.read_text()

    text = re.sub(
        r"(atr_stop_mult:\s*)\S+",
        lambda m: f"{m.group(1)}{stop_mult}",
        text,
    )
    text = re.sub(
        r"(atr_target_mult:\s*)\S+",
        lambda m: f"{m.group(1)}{target_mult}",
        text,
    )

    config_path.write_text(text)
    print(f"\nUpdated config/strategy.yml → atr_stop_mult={stop_mult}, atr_target_mult={target_mult}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()

    from_date = date.fromisoformat(args.from_date)
    to_date   = date.fromisoformat(args.to_date)

    results = _run_sweep(
        from_date=from_date,
        to_date=to_date,
        initial_cash=args.initial_cash,
        trades_per_week=args.trades_per_week,
        universe=args.universe,
    )

    _print_table(results)

    sorted_res = sorted(results, key=_sort_key)
    top2 = sorted_res[:2]

    print("\nTop 2 configurations:")
    for i, r in enumerate(top2, 1):
        pf = r.get("profit_factor") or 0.0
        print(
            f"  #{i}: stop_mult={r['atr_stop_mult']:.1f}  "
            f"target_mult={r['atr_target_mult']:.1f}  "
            f"CAGR={r['cagr']*100:+.1f}%  MaxDD={r['max_drawdown']*100:.1f}%  PF={pf:.2f}"
        )

    best = _pick_best(results)
    pf_best = best.get("profit_factor") or 0.0
    print(
        f"\nBest tradeoff: stop_mult={best['atr_stop_mult']:.1f}  "
        f"target_mult={best['atr_target_mult']:.1f}  "
        f"CAGR={best['cagr']*100:+.1f}%  MaxDD={best['max_drawdown']*100:.1f}%  "
        f"PF={pf_best:.2f}"
    )

    if args.no_update:
        print("\n(--no-update: config/strategy.yml NOT changed)")
    else:
        _update_strategy_config(best["atr_stop_mult"], best["atr_target_mult"])

    print("\nDone.")


if __name__ == "__main__":
    main()
