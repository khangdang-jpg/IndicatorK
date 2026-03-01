"""Weekly plan generation helpers for the backtest.

Two modes:
  plan     — load an existing weekly_plan.json once, reuse for all weeks.
  generate — for each week, call the active strategy on data up to that
             week's Monday (strict no-lookahead).
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from src.models import OHLCV, PortfolioState, WeeklyPlan

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def get_week_starts(from_date: date, to_date: date) -> list[date]:
    """Return Mondays of every calendar week that overlaps [from_date, to_date].

    Starts from the Monday of the week that contains *from_date* so that
    mid-week start dates still include that week's plan.

    Examples:
        from_date=2024-01-01 (Mon) → first week = 2024-01-01
        from_date=2024-01-03 (Wed) → first week = 2024-01-01  (same week)
    """
    # weekday() == 0 → Monday, so subtract to get Monday of same week
    first_monday = from_date - timedelta(days=from_date.weekday())

    weeks: list[date] = []
    current = first_monday
    while current <= to_date:
        weeks.append(current)
        current += timedelta(weeks=1)
    return weeks


def get_week_trading_days(week_start: date, week_end_inclusive: date) -> list[date]:
    """Return Mon–Fri dates within [week_start, week_end_inclusive]."""
    days: list[date] = []
    current = week_start
    while current <= week_end_inclusive:
        if current.weekday() < 5:  # 0=Mon … 4=Fri
            days.append(current)
        current += timedelta(days=1)
    return days


# ---------------------------------------------------------------------------
# Plan helpers
# ---------------------------------------------------------------------------

def load_plan_from_file(path: str) -> WeeklyPlan:
    """Deserialise a weekly_plan.json from disk."""
    with open(path) as f:
        return WeeklyPlan.from_dict(json.load(f))


def generate_plan_from_data(
    market_data: dict[str, list[OHLCV]],
    strategy,
    risk_config: dict,
    open_positions: dict[str, dict] | None = None,
) -> WeeklyPlan:
    """Run *strategy*.generate_weekly_plan on pre-sliced market data.

    Args:
        market_data: Historical OHLCV data sliced to exclude lookahead
        strategy: Strategy instance to generate the plan
        risk_config: Risk configuration dictionary
        open_positions: Dict of {symbol: {"qty": float, "entry_price": float}}
                        representing currently held positions from the engine.
                        Used in manual exit modes to generate HOLD/REDUCE/SELL signals.

    The PortfolioState is constructed from open_positions so the strategy
    can be portfolio-aware and generate appropriate exit signals.
    """
    # Construct PortfolioState from engine's open positions
    if open_positions:
        portfolio = PortfolioState(
            positions=open_positions,
            cash=0.0,  # Not used by strategy logic
            total_value=0.0,  # Not used by strategy logic
            allocation={"stock_pct": 0.0, "bond_fund_pct": 0.0, "cash_pct": 1.0},
            unrealized_pnl=0.0,
            realized_pnl=0.0,
        )
    else:
        portfolio = PortfolioState(
            positions={},
            cash=0.0,
            total_value=0.0,
            allocation={"stock_pct": 0.0, "bond_fund_pct": 0.0, "cash_pct": 1.0},
            unrealized_pnl=0.0,
            realized_pnl=0.0,
        )
    return strategy.generate_weekly_plan(market_data, portfolio, risk_config)
