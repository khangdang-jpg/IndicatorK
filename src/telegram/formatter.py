"""Message templates — weekly digest, alerts, status (no LLM)."""

from __future__ import annotations

from src.models import Alert, GuardrailsReport, PortfolioState, WeeklyPlan


def format_weekly_digest(
    plan: WeeklyPlan,
    portfolio_state: PortfolioState,
    guardrails: GuardrailsReport | None,
    risk_config: dict | None = None,
) -> str:
    """Format the weekly digest Telegram message."""
    lines = [
        f"*Weekly Plan — {plan.strategy_id} v{plan.strategy_version}*",
        f"Generated: {plan.generated_at[:16]}",
        "",
    ]

    # Top BUY candidates
    buys = [r for r in plan.recommendations if r.action == "BUY"][:10]
    if buys:
        lines.append("*Top BUY Candidates*")
        for r in buys:
            alloc_str = f" | Alloc {r.position_target_pct:.0%}" if r.position_target_pct else ""
            lines.append(
                f"  {r.symbol}: zone {r.buy_zone_low:,.0f}-{r.buy_zone_high:,.0f} "
                f"| SL {r.stop_loss:,.0f} | TP {r.take_profit:,.0f}{alloc_str}"
            )
        lines.append("")

    # Existing positions
    holds = [r for r in plan.recommendations if r.action in ("HOLD", "REDUCE", "SELL")]
    if holds:
        lines.append("*Positions*")
        for r in holds:
            lines.append(f"  {r.symbol}: {r.action} | SL {r.stop_loss:,.0f}")
            for bullet in r.rationale_bullets[:2]:
                lines.append(f"    - {bullet}")
        lines.append("")

    # Allocation config (shown only when risk_config is provided)
    if risk_config:
        alloc_cfg = risk_config.get("allocation", {})
        mode = alloc_cfg.get("alloc_mode", "fixed_pct")
        if mode == "risk_based":
            mode_detail = f"risk {alloc_cfg.get('risk_per_trade_pct', 0.01):.1%}/trade"
        else:
            mode_detail = f"fixed {alloc_cfg.get('fixed_alloc_pct_per_trade', 0.10):.0%}/trade"
        lines.append("*Allocation Config*")
        lines.append(
            f"  Mode: {mode} | {mode_detail} "
            f"| Range {alloc_cfg.get('min_alloc_pct', 0.03):.0%}–{alloc_cfg.get('max_alloc_pct', 0.15):.0%}"
        )
        lines.append("")

    # Allocation
    alloc = portfolio_state.allocation
    lines.append("*Allocation*")
    lines.append(
        f"  Stock: {alloc.get('stock_pct', 0):.1%} | "
        f"Bond+Fund: {alloc.get('bond_fund_pct', 0):.1%} | "
        f"Cash: {alloc.get('cash_pct', 0):.1%}"
    )
    targets = plan.allocation_targets
    lines.append(
        f"  Target: Stock {targets.get('stock', 0):.0%} | "
        f"Bond+Fund {targets.get('bond_fund', 0):.0%}"
    )
    lines.append(f"  Total value: {portfolio_state.total_value:,.0f}")
    lines.append("")

    # Guardrails
    if guardrails and guardrails.recommendations:
        lines.append("*Guardrails Warnings*")
        for rec in guardrails.recommendations:
            lines.append(f"  {rec}")
        lines.append("")

    # Notes
    if plan.notes:
        lines.append("*Notes*")
        for note in plan.notes:
            lines.append(f"  {note}")

    return "\n".join(lines)


def format_alert(alert: Alert) -> str:
    """Format a single price alert message."""
    if alert.alert_type == "STOP_LOSS_HIT":
        return (
            f"*STOP LOSS HIT* {alert.symbol}: "
            f"price={alert.current_price:,.0f} <= SL={alert.threshold:,.0f}"
        )
    if alert.alert_type == "TAKE_PROFIT_HIT":
        return (
            f"*TAKE PROFIT HIT* {alert.symbol}: "
            f"price={alert.current_price:,.0f} >= TP={alert.threshold:,.0f}"
        )
    if alert.alert_type == "ENTERED_BUY_ZONE":
        return (
            f"*BUY ZONE* {alert.symbol}: "
            f"price={alert.current_price:,.0f} (zone low={alert.threshold:,.0f})"
        )
    return f"*{alert.alert_type}* {alert.symbol}: price={alert.current_price:,.0f}"


def format_status(state: PortfolioState) -> str:
    """Format portfolio status for /status command."""
    lines = ["*Portfolio Status*", ""]

    if not state.positions:
        lines.append("No open positions.")
    else:
        lines.append("*Positions*")
        for sym, pos in sorted(state.positions.items()):
            pnl_str = f"{pos.unrealized_pnl:+,.0f}" if pos.unrealized_pnl else "0"
            lines.append(
                f"  {sym} ({pos.asset_class}): "
                f"{pos.qty:,.0f} @ {pos.avg_cost:,.0f} "
                f"| Now {pos.current_price:,.0f} "
                f"| PnL {pnl_str}"
            )

    lines.append("")
    lines.append("*Summary*")
    lines.append(f"  Cash: {state.cash:,.0f}")
    lines.append(f"  Total: {state.total_value:,.0f}")
    lines.append(f"  Unrealized PnL: {state.unrealized_pnl:+,.0f}")
    lines.append(f"  Realized PnL: {state.realized_pnl:+,.0f}")
    lines.append("")

    alloc = state.allocation
    lines.append("*Allocation*")
    lines.append(
        f"  Stock: {alloc.get('stock_pct', 0):.1%} | "
        f"Bond+Fund: {alloc.get('bond_fund_pct', 0):.1%} | "
        f"Cash: {alloc.get('cash_pct', 0):.1%}"
    )

    return "\n".join(lines)


def format_plan_summary(plan_data: dict) -> str:
    """Format weekly plan JSON for /plan command."""
    lines = [
        f"*Weekly Plan — {plan_data.get('strategy_id', '?')}*",
        f"Generated: {plan_data.get('generated_at', '?')[:16]}",
        "",
    ]

    recs = plan_data.get("recommendations", [])
    if not recs:
        lines.append("No recommendations.")
    else:
        for r in recs[:10]:
            pct = r.get("position_target_pct", 0)
            alloc_str = f" | Alloc {pct:.0%}" if pct else ""
            lines.append(
                f"  {r['symbol']}: {r['action']} "
                f"| Zone {r.get('buy_zone_low', 0):,.0f}-{r.get('buy_zone_high', 0):,.0f} "
                f"| SL {r.get('stop_loss', 0):,.0f}{alloc_str}"
            )

    notes = plan_data.get("notes", [])
    if notes:
        lines.append("")
        for n in notes:
            lines.append(f"  {n}")

    return "\n".join(lines)
