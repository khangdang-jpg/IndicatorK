#!/usr/bin/env python3
"""Strategy-parameter selector for TrendMomentumATR (hybrid mode).

Tests all combinations of:
  atr_stop_mult × atr_target_mult
  [1.8, 2.0, 2.2]  ×  [1.4, 1.6, 1.8, 2.0]
  ─────────────────────────────────────────
  TOTAL: 12 variants

Entry mode is fixed: Hybrid with weekly-close-confirmed breakouts.
  - breakout path: closes[-1] >= highs[-2], RSI >= rsi_breakout_min
  - pullback path: ATR mid-zone otherwise

Data is downloaded ONCE and replayed in memory across all variants.

Usage:
    python scripts/select_strategy.py
    python scripts/select_strategy.py --from 2025-02-01 --to 2026-02-25
    python scripts/select_strategy.py --workers 4          # parallel threads
    python scripts/select_strategy.py --update             # write to strategy.yml
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import OHLCV
from src.providers.base import PriceProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-memory provider
# ---------------------------------------------------------------------------

class _PreloadedProvider(PriceProvider):
    name = "preloaded"

    def __init__(self, data: dict[str, list[OHLCV]]) -> None:
        self._data = data

    def get_daily_history(self, symbol: str, start: date, end: date) -> list[OHLCV]:
        return [c for c in self._data.get(symbol, []) if start <= c.date <= end]

    def get_last_prices(self, symbols: list[str]) -> dict[str, float]:
        return {
            sym: self._data[sym][-1].close
            for sym in symbols if sym in self._data and self._data[sym]
        }


# ---------------------------------------------------------------------------
# Parameter grid
# ---------------------------------------------------------------------------

_STOP_MULTS   = [1.8, 2.0, 2.2]
_TARGET_MULTS = [1.4, 1.6, 1.8, 2.0]


def _build_grid() -> list[dict]:
    """Build 12 variants: atr_stop_mult × atr_target_mult."""
    return [
        {"atr_stop_mult": stop, "atr_target_mult": tgt}
        for stop in _STOP_MULTS
        for tgt in _TARGET_MULTS
    ]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _run_variant(
    variant: dict,
    preloaded: _PreloadedProvider,
    from_date: date,
    to_date: date,
    initial_cash: int,
    trades_per_week: int,
    tie_breaker: str,
    risk_config: dict,
    symbols: list[str],
) -> dict:
    from src.backtest.cli import _run_single
    from src.strategies.trend_momentum_atr import TrendMomentumATRStrategy

    strategy = TrendMomentumATRStrategy(params={
        "ma_short": 10, "ma_long": 30, "rsi_period": 14, "atr_period": 14,
        "rsi_breakout_min": 50,
        "entry_buffer_pct": 0.001,
        **variant,
    })

    engine = _run_single(
        from_date=from_date, to_date=to_date,
        initial_cash=initial_cash, order_size=None,
        trades_per_week=trades_per_week, mode="generate",
        plan_file="data/weekly_plan.json", tie_breaker=tie_breaker,
        provider=preloaded, strategy=strategy,
        risk_config=risk_config, symbols=symbols,
    )
    metrics = engine.compute_summary(from_date, to_date)
    metrics.update(variant)
    return metrics


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def _sort_key(r: dict) -> tuple:
    """CAGR↓, MaxDD↑, PF↓."""
    pf = r.get("profit_factor") or 0.0
    return (-r["cagr"], r["max_drawdown"], -pf)


def _pick_best(
    results: list[dict],
    min_trades: int,
    max_dd: float,
    min_pf: float,
) -> tuple[dict, str]:
    eligible = [
        r for r in results
        if r["num_trades"] >= min_trades
        and r["max_drawdown"] <= max_dd
        and (r.get("profit_factor") or 0.0) >= min_pf
    ]

    pool = eligible if eligible else results
    pool_sorted = sorted(pool, key=_sort_key)

    if not eligible:
        return pool_sorted[0], "highest CAGR [WARNING: no variant passed guardrails]"

    tier1 = [r for r in pool_sorted if r["cagr"] >= 0.09]
    if tier1:
        return tier1[0], "CAGR ≥ 9%"

    tier2 = [r for r in pool_sorted if r["max_drawdown"] <= 0.08]
    if tier2:
        return tier2[0], "highest CAGR with MaxDD ≤ 8%"

    return pool_sorted[0], "highest eligible CAGR"


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_COL = (
    f"{'rank':>4}  {'stop':>5}  {'tgt':>4}  "
    f"{'CAGR':>7}  {'MaxDD':>5}  {'  PF':>5}  {'WR':>4}  {'n':>3}  "
    f"{'hold':>6}  {'avgInv':>6}"
)
_SEP = "─" * len(_COL)


def _print_table(rows: list[dict], title: str) -> None:
    print(f"\n{title:^{len(_COL)}}")
    print(_SEP)
    print(_COL)
    print(_SEP)
    for i, r in enumerate(rows, 1):
        pf = r.get("profit_factor") or 0.0
        print(
            f"{i:>4}  {r['atr_stop_mult']:>5.1f}  {r['atr_target_mult']:>4.1f}  "
            f"{r['cagr']*100:>+6.1f}%  {r['max_drawdown']*100:>4.1f}%  {pf:>6.2f}  "
            f"{r['win_rate']*100:>3.0f}%  {r['num_trades']:>3d}  "
            f"{r['avg_hold_days']:>5.1f}d  {r.get('avg_invested_pct', 0)*100:>5.1f}%"
        )
    print(_SEP)


def _print_best_yaml(best: dict, rationale: str) -> None:
    pf = best.get("profit_factor") or 0.0
    print(
        f"\n# ── BEST VARIANT ({rationale}) ──────────────────────────────────────────\n"
        f"# CAGR={best['cagr']*100:+.1f}%  MaxDD={best['max_drawdown']*100:.1f}%  "
        f"PF={pf:.2f}  WR={best['win_rate']*100:.0f}%  "
        f"n={best['num_trades']}  avgHold={best['avg_hold_days']:.1f}d  "
        f"avgInv={best.get('avg_invested_pct', 0)*100:.1f}%\n"
        "# ── config/strategy.yml (paste under trend_momentum_atr:) ──────────────"
    )
    print(f"  atr_stop_mult: {best['atr_stop_mult']}")
    print(f"  atr_target_mult: {best['atr_target_mult']}")
    print("# ── config/optimizer.yml (paste as-is) ─────────────────────────────────")
    print(f"  best_atr_stop_mult: {best['atr_stop_mult']}")
    print(f"  best_atr_target_mult: {best['atr_target_mult']}")
    print("# ────────────────────────────────────────────────────────────────────────")


# ---------------------------------------------------------------------------
# Config updater
# ---------------------------------------------------------------------------

def _update_strategy_config(best: dict) -> None:
    config_path = Path(__file__).resolve().parent.parent / "config" / "strategy.yml"
    text = config_path.read_text()

    def _set(key: str, val: str) -> None:
        nonlocal text
        if re.search(rf"^\s+{key}:", text, re.MULTILINE):
            text = re.sub(
                rf"([ \t]+{key}:[ \t]*)\S.*",
                lambda m: f"{m.group(1)}{val}",
                text,
            )
        else:
            text = re.sub(
                r"(atr_target_mult:.*)",
                rf"\1\n  {key}: {val}",
                text, count=1,
            )

    _set("atr_stop_mult",   str(best["atr_stop_mult"]))
    _set("atr_target_mult", str(best["atr_target_mult"]))

    config_path.write_text(text)
    print("\nconfig/strategy.yml updated.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="TrendMomentumATR hybrid-mode selector (12 variants: stop × target)"
    )
    p.add_argument("--from",            dest="from_date",       default="2025-02-01")
    p.add_argument("--to",              dest="to_date",         default="2026-02-25")
    p.add_argument("--initial-cash",    type=int,               default=20_000_000)
    p.add_argument("--universe",        default="data/watchlist.txt")
    p.add_argument("--tie-breaker",     default="worst",        choices=["worst", "best"])
    p.add_argument("--workers",         type=int,               default=1,
                   help="Thread pool size (default 1 = sequential)")
    p.add_argument("--top",             type=int,               default=12,
                   help="Rows in the summary table (default 12 = all)")
    p.add_argument("--trades-per-week", type=int,               default=None,
                   help="Override trades/week (default: 4)")
    p.add_argument("--min-trades",      type=int,               default=10)
    p.add_argument("--max-dd",          type=float,             default=0.10,
                   help="Max drawdown guardrail (default 0.10 = 10%%)")
    p.add_argument("--min-pf",          type=float,             default=1.5,
                   help="Min profit factor guardrail (default 1.5)")
    p.add_argument("--update",          action="store_true",
                   help="Write best config to config/strategy.yml")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    from_date = date.fromisoformat(args.from_date)
    to_date   = date.fromisoformat(args.to_date)

    from src.backtest.cli import _get_provider_with_fallback
    from src.utils.config import get_risk_config, load_watchlist
    from src.utils.logging_setup import setup_logging

    setup_logging()
    logging.getLogger("src").setLevel(logging.WARNING)

    risk_config = get_risk_config()
    symbols     = load_watchlist(args.universe)
    grid        = _build_grid()

    trades_per_week = args.trades_per_week or 4

    print(
        f"\nStrategy-variant selector  |  {len(grid)} variants (hybrid: stop × target)\n"
        f"Grid: {len(_STOP_MULTS)} stop_mults × {len(_TARGET_MULTS)} target_mults  "
        f"|  {from_date} → {to_date}  |  tie_breaker={args.tie_breaker}"
    )
    print(
        f"trades/week={trades_per_week}  "
        f"guardrails: MaxDD≤{args.max_dd:.0%}  PF≥{args.min_pf}  n≥{args.min_trades}\n"
    )

    # ------------------------------------------------------------------
    # Fetch data once
    # ------------------------------------------------------------------
    history_start = from_date - timedelta(weeks=52)
    live = _get_provider_with_fallback()
    print(f"Fetching {len(symbols)} symbols ({history_start} → {to_date}) …")

    all_data: dict[str, list[OHLCV]] = {}
    for sym in symbols:
        try:
            candles = live.get_daily_history(sym, history_start, to_date)
        except Exception as exc:
            logger.warning("fetch failed for %s: %s", sym, exc)
            candles = []
        if candles:
            all_data[sym] = sorted(candles, key=lambda c: c.date)

    print(f"  {len(all_data)}/{len(symbols)} symbols ready.\n")
    if not all_data:
        print("ERROR: no price data. Aborting.")
        sys.exit(1)

    preloaded = _PreloadedProvider(all_data)

    # ------------------------------------------------------------------
    # Run all variants
    # ------------------------------------------------------------------
    run_kw = dict(
        preloaded=preloaded, from_date=from_date, to_date=to_date,
        initial_cash=args.initial_cash, trades_per_week=trades_per_week,
        tie_breaker=args.tie_breaker, risk_config=risk_config, symbols=symbols,
    )

    results: list[dict] = []

    def _progress(r: dict, idx: int) -> str:
        pf = r.get("profit_factor") or 0.0
        return (
            f"  [{idx:2d}/{len(grid)}] stop={r['atr_stop_mult']:.1f}  tgt={r['atr_target_mult']:.1f}  "
            f"CAGR={r['cagr']*100:>+5.1f}%  DD={r['max_drawdown']*100:>4.1f}%  "
            f"PF={pf:>4.2f}  n={r['num_trades']:>2d}"
        )

    print(f"Running {len(grid)} variants "
          f"({'parallel ' + str(args.workers) + ' threads' if args.workers > 1 else 'sequential'}) …")

    if args.workers > 1:
        futures_map: dict = {}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for i, v in enumerate(grid):
                futures_map[pool.submit(_run_variant, v, **run_kw)] = (i + 1, v)
            done = 0
            for fut in as_completed(futures_map):
                idx, _ = futures_map[fut]
                try:
                    r = fut.result()
                    results.append(r)
                    done += 1
                    print(_progress(r, done))
                except Exception as exc:
                    logger.warning("variant %d failed: %s", idx, exc)
    else:
        for idx, variant in enumerate(grid, 1):
            r = _run_variant(variant, **run_kw)
            results.append(r)
            print(_progress(r, idx))

    # ------------------------------------------------------------------
    # Rank and display
    # ------------------------------------------------------------------
    all_sorted = sorted(results, key=_sort_key)

    eligible = [
        r for r in all_sorted
        if r["num_trades"] >= args.min_trades
        and r["max_drawdown"] <= args.max_dd
        and (r.get("profit_factor") or 0.0) >= args.min_pf
    ]
    n_excluded = len(results) - len(eligible)
    if n_excluded:
        print(f"\n  Note: {n_excluded} variant(s) excluded by guardrails "
              f"(n<{args.min_trades} or MaxDD>{args.max_dd:.0%} or PF<{args.min_pf}).")

    display = sorted(eligible if eligible else all_sorted, key=_sort_key)
    _print_table(
        display[:args.top],
        title=f"TOP {min(args.top, len(display))} VARIANTS — CAGR↓  MaxDD↑  PF↓",
    )

    best, rationale = _pick_best(results, args.min_trades, args.max_dd, args.min_pf)
    _print_best_yaml(best, rationale)

    print(
        "\n[Mode] Hybrid: weekly-close-confirmed breakout (highs[-2]) or pullback.  "
        "SL/TP anchored to entry_price."
    )

    if args.update:
        _update_strategy_config(best)
    else:
        print("(Pass --update to write best config to config/strategy.yml)")

    sys.exit(0)


if __name__ == "__main__":
    main()
