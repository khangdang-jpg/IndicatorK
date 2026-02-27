"""Message templates — weekly digest, alerts, status (optional LLM scoring)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from src.models import Alert, GuardrailsReport, PortfolioState, WeeklyPlan

if TYPE_CHECKING:
    from src.ai.gemini_analyzer import AIAnalysis

_ENTRY_ICON = {"breakout": "⬆", "pullback": "⬇"}
_ACTION_ICON = {"BUY": "🟢", "HOLD": "🔵", "REDUCE": "🟡", "SELL": "🔴"}
_CACHE_PATH = "data/prices_cache.json"


def _alloc_vnd(pct: float, total: float) -> int:
    """Round position allocation to nearest 100k VND."""
    return round(pct * total / 100_000) * 100_000


def _load_cached_prices(symbols: list[str]) -> dict[str, float]:
    """Read last known prices from prices_cache.json."""
    p = Path(_CACHE_PATH)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
        return {
            sym: float(data[sym]["last_price"])
            for sym in symbols
            if sym in data and "last_price" in data[sym]
        }
    except Exception:
        return {}


def _ai_score_tag(ai_analysis: AIAnalysis | None, symbol: str) -> str:
    """Return compact AI score tag like '  AI 8/10' or empty string."""
    if not ai_analysis or not ai_analysis.generated:
        return ""
    ai = ai_analysis.scores.get(symbol)
    if not ai:
        return ""
    return f"  AI {ai.score}/10"


def _zone_label(price: float, low: float, high: float) -> str:
    """Return a compact zone-distance label for a given price."""
    if low <= price <= high:
        return "✅ in zone"
    if price > high:
        pct = (price - high) / high * 100
        return f"⬆ {pct:.1f}% above zone"
    pct = (low - price) / low * 100
    return f"⬇ {pct:.1f}% below zone"


def format_weekly_digest(
    plan: WeeklyPlan,
    portfolio_state: PortfolioState,
    guardrails: GuardrailsReport | None,
    ai_analysis: AIAnalysis | None = None,
) -> str:
    """Format the weekly digest Telegram message."""
    total = portfolio_state.total_value
    lines = [
        f"📊 *Weekly Plan — S1 v{plan.strategy_version}*",
        f"📅 {plan.generated_at[:10]}  💰 {total:,.0f} ₫",
        "",
    ]

    buys = [r for r in plan.recommendations if r.action == "BUY"][:10]
    if buys:
        lines.append(f"*🟢 BUY ({len(buys)})*")
        for r in buys:
            icon = _ENTRY_ICON.get(r.entry_type, "·")
            vnd = _alloc_vnd(r.position_target_pct, total) if r.position_target_pct and total else 0
            alloc_str = f"  Alloc {vnd:,.0f} ₫" if vnd else ""
            ai_tag = _ai_score_tag(ai_analysis, r.symbol)
            lines.append(f"`{r.symbol}` {icon} {r.entry_type.capitalize()}{alloc_str}{ai_tag}")
            lines.append(f"  Entry {r.entry_price:,.0f}  Zone {r.buy_zone_low:,.0f}–{r.buy_zone_high:,.0f}")
            lines.append(f"  SL {r.stop_loss:,.0f}  TP {r.take_profit:,.0f}")
        lines.append("")

    holds = [r for r in plan.recommendations if r.action in ("HOLD", "REDUCE", "SELL")]
    if holds:
        lines.append("*📋 Positions*")
        for r in holds:
            icon = _ACTION_ICON.get(r.action, "·")
            ai_tag = _ai_score_tag(ai_analysis, r.symbol)
            lines.append(f"  {icon} `{r.symbol}` {r.action}  SL {r.stop_loss:,.0f}{ai_tag}")
        lines.append("")

    alloc = portfolio_state.allocation
    targets = plan.allocation_targets
    lines.append("*💼 Portfolio*")
    lines.append(
        f"  Stock {alloc.get('stock_pct', 0):.0%}  "
        f"Bond {alloc.get('bond_fund_pct', 0):.0%}  "
        f"Cash {alloc.get('cash_pct', 0):.0%}"
    )
    lines.append(
        f"  Target → Stock {targets.get('stock', 0):.0%}  "
        f"Bond {targets.get('bond_fund', 0):.0%}"
    )

    if guardrails and guardrails.recommendations:
        lines.append("")
        lines.append("*⚠️ Guardrails*")
        for rec in guardrails.recommendations:
            lines.append(f"  {rec}")

    # AI Analysis section
    if ai_analysis and ai_analysis.generated:
        from src.ai.gemini_analyzer import format_ai_section
        ai_section = format_ai_section(
            ai_analysis,
            [r.to_dict() for r in plan.recommendations],
        )
        if ai_section:
            lines.append(ai_section)

    return "\n".join(lines)


def format_alert(alert: Alert) -> str:
    """Format a single price alert message."""
    if alert.alert_type == "STOP_LOSS_HIT":
        return (
            f"🔴 *STOP LOSS* `{alert.symbol}`\n"
            f"Price {alert.current_price:,.0f} ≤ SL {alert.threshold:,.0f}"
        )
    if alert.alert_type == "TAKE_PROFIT_HIT":
        return (
            f"🟢 *TAKE PROFIT* `{alert.symbol}`\n"
            f"Price {alert.current_price:,.0f} ≥ TP {alert.threshold:,.0f}"
        )
    if alert.alert_type == "ENTERED_BUY_ZONE":
        return (
            f"🔵 *BUY ZONE* `{alert.symbol}`\n"
            f"Price {alert.current_price:,.0f}  (zone ≥ {alert.threshold:,.0f})"
        )
    return f"*{alert.alert_type}* `{alert.symbol}`: {alert.current_price:,.0f}"


def format_status(state: PortfolioState) -> str:
    """Format portfolio status for /status command."""
    lines = ["*💼 Portfolio Status*", ""]

    if not state.positions:
        lines.append("No open positions.")
    else:
        lines.append("*Positions*")
        for sym, pos in sorted(state.positions.items()):
            pnl = pos.unrealized_pnl or 0
            lines.append(
                f"  `{sym}`: {pos.qty:,.0f} @ {pos.avg_cost:,.0f}"
                f" → {pos.current_price:,.0f}  PnL {pnl:+,.0f}"
            )

    lines.append("")
    lines.append(f"Total {state.total_value:,.0f} ₫  Cash {state.cash:,.0f}")
    lines.append(
        f"PnL  Unrealized {state.unrealized_pnl:+,.0f}  "
        f"Realized {state.realized_pnl:+,.0f}"
    )
    lines.append("")
    alloc = state.allocation
    lines.append(
        f"Stock {alloc.get('stock_pct', 0):.0%}  "
        f"Bond {alloc.get('bond_fund_pct', 0):.0%}  "
        f"Cash {alloc.get('cash_pct', 0):.0%}"
    )
    return "\n".join(lines)


def format_plan_summary(plan_data: dict, total_value: float = 0.0) -> str:
    """Format weekly plan for /plan command with cached current prices."""
    date_str = plan_data.get("generated_at", "?")[:10]
    balance_str = f"  💰 {total_value:,.0f} ₫" if total_value else ""
    lines = [
        f"📊 *{plan_data.get('strategy_id', '?')} v{plan_data.get('strategy_version', '?')}*",
        f"📅 {date_str}{balance_str}",
        "",
    ]

    recs = plan_data.get("recommendations", [])
    if not recs:
        lines.append("No recommendations.")
        return "\n".join(lines)

    cached = _load_cached_prices([r["symbol"] for r in recs])

    buys = [r for r in recs if r.get("action") == "BUY"]
    others = [r for r in recs if r.get("action") != "BUY"]

    if buys:
        lines.append(f"*🟢 BUY ({len(buys)})*")
        for r in buys:
            sym = r["symbol"]
            icon = _ENTRY_ICON.get(r.get("entry_type", ""), "·")
            entry = r.get("entry_price", 0)
            pct = r.get("position_target_pct", 0)
            vnd = _alloc_vnd(pct, total_value) if pct and total_value else 0
            alloc_str = f"  {vnd:,.0f} ₫" if vnd else (f"  {pct:.0%}" if pct else "")

            lines.append(f"`{sym}` {icon} {r.get('entry_type','').capitalize()}{alloc_str}")

            now = cached.get(sym)
            if now:
                label = _zone_label(now, r.get("buy_zone_low", 0), r.get("buy_zone_high", 0))
                lines.append(f"  Now {now:,.0f}  {label}")

            lines.append(
                f"  Entry {entry:,.0f}  "
                f"Zone {r.get('buy_zone_low', 0):,.0f}–{r.get('buy_zone_high', 0):,.0f}"
            )
            lines.append(f"  SL {r.get('stop_loss', 0):,.0f}  TP {r.get('take_profit', 0):,.0f}")

    if others:
        lines.append("")
        lines.append("*📋 Positions*")
        for r in others:
            icon = _ACTION_ICON.get(r.get("action", ""), "·")
            sym = r["symbol"]
            now = cached.get(sym)
            now_str = f"  now {now:,.0f}" if now else ""
            lines.append(
                f"  {icon} `{sym}` {r.get('action')}{now_str}  SL {r.get('stop_loss', 0):,.0f}"
            )

    return "\n".join(lines)
