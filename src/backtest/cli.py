"""CLI entry point for the backtest command.

Run:
    python scripts/backtest.py --from 2025-05-01 --to 2026-02-25
    python3 scripts/backtest.py --from 2025-02-01 --to 2026-02-25 --run-range
    python -m src.backtest   --from 2025-05-01 --to 2026-02-25 --run-range

Recommended defaults match the spec:
    --initial-cash 10000000 --order-size 1000000 --trades-per-week 4
    --universe data/watchlist.txt --mode generate
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="backtest",
        description="IndicatorK strategy backtester",
    )
    p.add_argument("--from", dest="from_date", required=True, metavar="YYYY-MM-DD",
                   help="Backtest start date (inclusive)")
    p.add_argument("--to", dest="to_date", required=True, metavar="YYYY-MM-DD",
                   help="Backtest end date (inclusive)")
    p.add_argument("--initial-cash", type=int, default=20_000_000,
                   help="Starting cash in VND (default: 20,000,000)")
    p.add_argument("--order-size", type=int, default=None,
                   help="[DEPRECATED] Fixed VND per trade. Omit to use alloc_mode from config/risk.yml.")
    p.add_argument("--trades-per-week", type=int, default=4,
                   help="Max new positions to open each week (default: 4)")
    p.add_argument("--universe", default="data/watchlist.txt",
                   help="Path to watchlist file (default: data/watchlist.txt)")
    p.add_argument("--entry", default="mid_zone", choices=["mid_zone"],
                   help="Entry price rule (only mid_zone supported)")
    p.add_argument("--exit", default="touch", choices=["touch"],
                   help="Exit rule (only touch supported)")
    p.add_argument("--tie-breaker", default="worst", choices=["worst", "best"],
                   help="Same-day SL+TP tie-breaker: worst=SL first, best=TP first")
    p.add_argument("--mode", default="generate", choices=["plan", "generate"],
                   help=(
                       "plan: reuse data/weekly_plan.json for every week; "
                       "generate: regenerate plan per week using active strategy"
                   ))
    p.add_argument("--plan-file", default="data/weekly_plan.json",
                   help="Weekly plan JSON to use in --mode plan (default: data/weekly_plan.json)")
    p.add_argument("--run-range", action="store_true",
                   help=(
                       "Run both worst and best tie-breakers and produce "
                       "labelled outputs + range_summary.json"
                   ))
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Core simulation
# ---------------------------------------------------------------------------

def _run_single(
    from_date: date,
    to_date: date,
    initial_cash: int,
    order_size: int | None,
    trades_per_week: int,
    mode: str,
    plan_file: str,
    tie_breaker: str,
    provider,
    strategy,
    risk_config: dict,
    symbols: list[str],
):
    """Run one backtest with a specific tie-breaker; return the engine."""
    from src.backtest.engine import BacktestEngine
    from src.backtest.weekly_generator import (
        generate_plan_from_data,
        get_week_starts,
        load_plan_from_file,
    )

    # ------------------------------------------------------------------
    # 1. Pre-fetch all daily history (from_date - 52 weeks → to_date)
    # ------------------------------------------------------------------
    history_start = from_date - timedelta(weeks=52)
    all_history_list: dict[str, list] = {}   # symbol → [OHLCV]
    all_history_map: dict[str, dict] = {}    # symbol → {date: OHLCV}

    logger.info(
        "Fetching daily history for %d symbols (%s → %s)…",
        len(symbols), history_start, to_date,
    )
    for sym in symbols:
        try:
            candles = provider.get_daily_history(sym, history_start, to_date)
        except Exception as exc:
            logger.warning("get_daily_history failed for %s: %s", sym, exc)
            candles = []
        if candles:
            sorted_candles = sorted(candles, key=lambda c: c.date)
            all_history_list[sym] = sorted_candles
            all_history_map[sym] = {c.date: c for c in sorted_candles}

    logger.info(
        "Data fetched for %d/%d symbols", len(all_history_list), len(symbols)
    )

    # ------------------------------------------------------------------
    # 2. Initialise engine
    # ------------------------------------------------------------------
    engine = BacktestEngine(
        initial_cash=initial_cash,
        order_size=order_size if order_size else None,  # None = pct-based sizing
        tie_breaker=tie_breaker,
    )

    # ------------------------------------------------------------------
    # 3. Load static plan once (plan mode)
    # ------------------------------------------------------------------
    static_plan = None
    if mode == "plan":
        static_plan = load_plan_from_file(plan_file)
        logger.info("Plan mode: loaded %s", plan_file)

    # ------------------------------------------------------------------
    # 4. Week-by-week iteration
    # ------------------------------------------------------------------
    week_starts = get_week_starts(from_date, to_date)
    logger.info(
        "Simulating %d weeks (%s → %s) tie_breaker=%s",
        len(week_starts), from_date, to_date, tie_breaker,
    )

    # pending_entries: {symbol: (entry_price, sl, tp, position_target_pct, entry_type, earliest_entry_date)}
    # earliest_entry_date: None for pullback; Monday of T+1 for breakout (T+1 enforcement).
    # Cleared at the end of each week (entries expire if not filled).
    pending_entries: dict[str, tuple] = {}

    for week_idx, week_start in enumerate(week_starts):
        week_end = week_start + timedelta(days=4)  # Friday

        # ------------------------------------------------------------------
        # 4a. Generate (or reuse) the weekly plan
        # ------------------------------------------------------------------
        if static_plan is not None:
            plan = static_plan
        else:
            # Slice only candles before week_start (strict no-lookahead)
            week_market_data = {
                sym: [c for c in candles if c.date < week_start]
                for sym, candles in all_history_list.items()
                if any(c.date < week_start for c in candles)
            }
            if not week_market_data:
                logger.warning("No market data before %s, skipping week", week_start)
                pending_entries.clear()
                continue
            try:
                plan = generate_plan_from_data(week_market_data, strategy, risk_config)
                logger.debug(
                    "Week %d (%s): %d recommendations",
                    week_idx + 1, week_start, len(plan.recommendations),
                )
            except Exception as exc:
                logger.warning(
                    "Plan generation failed for week %s: %s", week_start, exc
                )
                pending_entries.clear()
                continue

        # ------------------------------------------------------------------
        # 4b. Queue new pending entries from BUY recommendations
        # ------------------------------------------------------------------
        open_symbols = {t.symbol for t in engine.open_trades}
        buys = [
            r
            for r in plan.recommendations
            if r.action == "BUY"
            and r.symbol not in open_symbols
            and r.symbol not in pending_entries
            and r.symbol in all_history_map          # must have data
            and r.buy_zone_low > 0                   # sanity check
            and r.stop_loss > 0
            and r.take_profit > 0
        ][:trades_per_week]

        for rec in buys:
            # entry_price is explicit on the Recommendation; fall back to zone
            # midpoint for backward compat with old weekly_plan.json (entry_price=0.0).
            ep = rec.entry_price if rec.entry_price > 0 else (rec.buy_zone_low + rec.buy_zone_high) / 2.0
            pending_entries[rec.symbol] = (
                ep, rec.stop_loss, rec.take_profit,
                rec.position_target_pct, rec.entry_type,
                rec.earliest_entry_date,
            )

        # ------------------------------------------------------------------
        # 4c. Daily simulation through Mon–Fri of this week
        # ------------------------------------------------------------------
        sim_start = max(week_start, from_date)
        sim_end = min(week_end, to_date)
        current_day = sim_start

        while current_day <= sim_end:
            # Skip weekends (VN market is Mon–Fri)
            if current_day.weekday() >= 5:
                current_day += timedelta(days=1)
                continue

            # Collect all candles needed today
            relevant = (
                set(pending_entries.keys())
                | {t.symbol for t in engine.open_trades}
            )
            candles_today = {
                sym: all_history_map[sym][current_day]
                for sym in relevant
                if current_day in all_history_map.get(sym, {})
            }

            # Try to fill pending entries
            filled: list[str] = []
            for sym, (entry, sl, tp, pct, etype, eed) in list(pending_entries.items()):
                candle = candles_today.get(sym)
                if candle and engine.try_enter(
                    sym, entry, sl, tp, candle,
                    position_target_pct=pct,
                    entry_type=etype,
                    earliest_entry_date=eed,
                ):
                    logger.debug(
                        "  ENTER %s @ %.2f (%.0f%% equity) on %s", sym, entry, pct * 100, current_day
                    )
                    filled.append(sym)
            for sym in filled:
                del pending_entries[sym]

            # Check SL/TP on existing open trades
            engine.process_day(candles_today, current_day)

            current_day += timedelta(days=1)

        # Pending entries expire at week-end; fresh plan next Monday
        pending_entries.clear()

    return engine


# ---------------------------------------------------------------------------
# Provider helper with automatic fallback
# ---------------------------------------------------------------------------

def _get_provider_with_fallback():
    """Build the composite provider; fall back to Simplize → TCBS → cache.

    Chain:
        1. vnstock (preferred — requires pandas)
        2. Simplize HTTP API (secondary)
        3. TCBS HTTP API (last live fallback — free, no auth, reliable for VN stocks)
        4. Local cache (offline last resort)

    This lets the backtest run even when vnstock/pandas is not installed.
    """
    from src.utils.config import get_provider, load_yaml

    try:
        return get_provider()
    except Exception as primary_err:
        logger.warning(
            "vnstock provider failed (%s). Falling back to Simplize → TCBS → cache.",
            primary_err,
        )

    from pathlib import Path as _Path

    from src.providers.cache_provider import CacheProvider
    from src.providers.composite_provider import CompositeProvider
    from src.providers.http_provider import HttpProvider

    cfg = load_yaml("config/providers.yml")
    cache_path = str(
        _Path(__file__).resolve().parent.parent.parent
        / cfg.get("cache_path", "data/prices_cache.json")
    )

    # Primary fallback: Simplize API (from providers.yml)
    simplize = HttpProvider(
        base_url=cfg.get("http", {}).get(
            "base_url", "https://api.simplize.vn/api/company/get-chart"
        ),
        timeout=cfg.get("http", {}).get("timeout", 15),
        retries=1,  # fail fast — TCBS is ready behind it
    )

    # Secondary fallback: TCBS public API (Techcombank Securities)
    # Free, no auth, reliable daily OHLCV for all HOSE/HNX/UPCOM symbols.
    # Response shape: {"data": [{"tradingDate": "...", "open": ..., ...}]}
    tcbs = HttpProvider(
        base_url=(
            "https://apipubaws.tcbs.com.vn"
            "/stock-insight/v1/stock/bars-long-term"
        ),
        timeout=20,
        retries=2,
        extra_params={"type": "stock", "resolution": "D"},
    )

    cache = CacheProvider(cache_path=cache_path)
    logger.info("Using fallback provider chain: Simplize → TCBS → cache")
    return CompositeProvider(primary=simplize, secondary=tcbs, cache=cache)


# ---------------------------------------------------------------------------
# Public run function (also used by tests)
# ---------------------------------------------------------------------------

def run_backtest(
    from_date: date,
    to_date: date,
    initial_cash: int = 10_000_000,
    order_size: int | None = None,
    trades_per_week: int = 4,
    universe: str = "data/watchlist.txt",
    tie_breaker: str = "worst",
    mode: str = "generate",
    plan_file: str = "data/weekly_plan.json",
    run_range: bool = False,
    output_base: str = "reports",
    provider=None,
    strategy=None,
    risk_config: dict | None = None,
    symbols: list[str] | None = None,
) -> Path:
    """Orchestrate a full backtest and write all reports.

    Returns the output directory path.
    """
    from src.backtest.reporter import (
        build_range_summary,
        make_output_dir,
        write_equity_curve,
        write_summary,
        write_trades,
    )
    from src.utils.config import (
        get_provider,
        get_risk_config,
        get_strategy,
        load_watchlist,
    )
    from src.utils.logging_setup import setup_logging

    setup_logging()

    if provider is None:
        provider = _get_provider_with_fallback()
    if strategy is None:
        strategy = get_strategy()
    if risk_config is None:
        risk_config = get_risk_config()
    if symbols is None:
        symbols = load_watchlist(universe)

    output_dir = make_output_dir(output_base)

    tie_breakers = ["worst", "best"] if run_range else [tie_breaker]
    summaries: dict[str, dict] = {}

    for tb in tie_breakers:
        logger.info("--- Running backtest: tie_breaker=%s ---", tb)
        engine = _run_single(
            from_date=from_date,
            to_date=to_date,
            initial_cash=initial_cash,
            order_size=order_size,
            trades_per_week=trades_per_week,
            mode=mode,
            plan_file=plan_file,
            tie_breaker=tb,
            provider=provider,
            strategy=strategy,
            risk_config=risk_config,
            symbols=symbols,
        )
        metrics = engine.compute_summary(from_date, to_date)
        metrics["tie_breaker"] = tb          # tag which scenario this is
        summaries[tb] = metrics

        # Equity curve and trades are labelled (worst/best have different values)
        label = tb if run_range else ""
        write_equity_curve(output_dir, engine.equity_curve, label=label)
        write_trades(output_dir, engine.closed_trades, label=label)

    # Always exactly ONE summary.json
    if run_range:
        summary_data = build_range_summary(summaries["worst"], summaries["best"])
    else:
        summary_data = summaries[tie_breaker]
    write_summary(output_dir, summary_data)

    return output_dir


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    from_date = date.fromisoformat(args.from_date)
    to_date = date.fromisoformat(args.to_date)

    output_dir = run_backtest(
        from_date=from_date,
        to_date=to_date,
        initial_cash=args.initial_cash,
        order_size=args.order_size,
        trades_per_week=args.trades_per_week,
        universe=args.universe,
        tie_breaker=args.tie_breaker,
        mode=args.mode,
        plan_file=args.plan_file,
        run_range=args.run_range,
    )

    print(f"Backtest complete. Results written to: {output_dir}")
