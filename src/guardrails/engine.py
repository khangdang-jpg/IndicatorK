"""Guardrails engine — data quality + performance checks -> JSON report."""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from pathlib import Path

from src.models import (
    GuardrailsReport,
    PortfolioState,
    ProviderHealth,
    StrategyHealth,
)

logger = logging.getLogger(__name__)


def run_guardrails(
    provider_health: ProviderHealth,
    strategy_id: str,
    portfolio_state: PortfolioState,
    snapshots: list[dict],
    risk_config: dict,
) -> GuardrailsReport:
    """Run all guardrail checks and produce a structured report.

    Args:
        provider_health: health stats from composite provider
        strategy_id: current strategy ID
        portfolio_state: current portfolio state
        snapshots: rows from portfolio_weekly.csv (list of dicts)
        risk_config: from config/risk.yml
    """
    recommendations = []
    gc = risk_config.get("guardrails", {})

    # --- Data quality checks ---
    err_threshold = gc.get("provider_error_rate_threshold", 0.30)
    miss_threshold = gc.get("provider_missing_rate_threshold", 0.50)

    if provider_health.error_rate > err_threshold:
        recommendations.append(
            f"SWITCH_PROVIDER: error rate {provider_health.error_rate:.0%} "
            f"exceeds threshold {err_threshold:.0%}"
        )

    if provider_health.missing_rate > miss_threshold:
        recommendations.append(
            f"SWITCH_PROVIDER: missing rate {provider_health.missing_rate:.0%} "
            f"exceeds threshold {miss_threshold:.0%}"
        )

    # --- Performance checks from snapshots ---
    rolling_weeks = risk_config.get("rolling_weeks", 12)
    benchmark_annual = risk_config.get("benchmark_cagr_annual", 0.09)
    max_dd = risk_config.get("max_drawdown", 0.15)
    max_turnover = risk_config.get("max_turnover_weekly", 0.20)
    min_cagr_ratio = gc.get("min_cagr_vs_benchmark_ratio", 0.5)

    rolling_cagr = None
    drawdown = None
    turnover = None
    weeks_tracked = len(snapshots)

    if len(snapshots) >= 2:
        rolling_cagr = _compute_rolling_cagr(snapshots, rolling_weeks)
        drawdown = _compute_max_drawdown(snapshots)
        turnover = _compute_turnover(portfolio_state, snapshots)

        if rolling_cagr is not None:
            benchmark_weekly = (1 + benchmark_annual) ** (1 / 52) - 1
            target = benchmark_weekly * rolling_weeks
            if rolling_cagr < target * min_cagr_ratio:
                recommendations.append(
                    f"SWITCH_STRATEGY: rolling {rolling_weeks}w return "
                    f"{rolling_cagr:.2%} below {target * min_cagr_ratio:.2%} "
                    f"threshold (current: {strategy_id})"
                )

        if drawdown is not None and drawdown > max_dd:
            recommendations.append(
                f"DE_RISK: max drawdown {drawdown:.1%} exceeds "
                f"threshold {max_dd:.0%} — reduce position targets"
            )

    strategy_health = StrategyHealth(
        rolling_cagr=rolling_cagr,
        drawdown=drawdown,
        turnover=turnover,
        weeks_tracked=weeks_tracked,
    )

    return GuardrailsReport(
        generated_at=datetime.utcnow().isoformat(),
        provider_health=provider_health,
        strategy_health=strategy_health,
        recommendations=recommendations,
    )


def save_guardrails_report(
    report: GuardrailsReport, path: str = "data/guardrails_report.json"
) -> None:
    """Write guardrails report to JSON file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(report.to_dict(), f, indent=2)
    logger.info("Guardrails report saved to %s", path)


def load_guardrails_report(
    path: str = "data/guardrails_report.json",
) -> GuardrailsReport | None:
    """Load the latest guardrails report from file."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        with open(p) as f:
            return GuardrailsReport.from_dict(json.load(f))
    except Exception as e:
        logger.warning("Failed to load guardrails report: %s", e)
        return None


def _compute_rolling_cagr(
    snapshots: list[dict], weeks: int
) -> float | None:
    """Compute rolling return over the last N weeks from snapshots."""
    if len(snapshots) < 2:
        return None

    recent = snapshots[-min(weeks, len(snapshots)) :]
    start_val = recent[0]["total_value"]
    end_val = recent[-1]["total_value"]

    if start_val <= 0:
        return None

    n_weeks = len(recent) - 1
    if n_weeks <= 0:
        return None

    return (end_val / start_val) - 1.0


def _compute_max_drawdown(snapshots: list[dict]) -> float | None:
    """Compute maximum drawdown from peak across all snapshots."""
    if not snapshots:
        return None

    values = [s["total_value"] for s in snapshots if s["total_value"] > 0]
    if not values:
        return None

    peak = values[0]
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _compute_turnover(
    portfolio_state: PortfolioState,
    snapshots: list[dict],
) -> float | None:
    """Estimate turnover from realized PnL change vs portfolio value."""
    if len(snapshots) < 2 or portfolio_state.total_value <= 0:
        return None

    recent_realized = snapshots[-1].get("realized_pnl", 0)
    prev_realized = snapshots[-2].get("realized_pnl", 0)
    delta = abs(recent_realized - prev_realized)
    return delta / portfolio_state.total_value
