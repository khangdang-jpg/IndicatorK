"""Message templates — weekly digest, alerts, status (optional LLM scoring)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from src.models import Alert, GuardrailsReport, PortfolioState, WeeklyPlan

if TYPE_CHECKING:
    from src.ai.groq_analyzer import AIAnalysis

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


def _zone_label(price: float, low: float, high: float) -> str:
    """Return a compact zone-distance label for a given price."""
    if low <= price <= high:
        return "✅ in zone"
    if price > high:
        pct = (price - high) / high * 100
        return f"⬆ {pct:.1f}% above zone"
    pct = (low - price) / low * 100
    return f"⬇ {pct:.1f}% below zone"


def _format_unified_analysis(ai_analysis, plan, recommendations) -> str:
    """Create unified analysis combining technical AI + news insights."""
    import re

    lines = ["", "*📊 Market Analysis*"]

    # Get technical analysis scores
    tech_scores = {}
    market_context = ""
    if ai_analysis and ai_analysis.generated:
        tech_scores = ai_analysis.scores if hasattr(ai_analysis, 'scores') else {}
        market_context = ai_analysis.market_context if hasattr(ai_analysis, 'market_context') else ""

    # Get news analysis scores
    news_scores = {}
    if hasattr(plan, 'news_analysis') and plan.news_analysis and plan.news_analysis.get('symbol_scores'):
        for score_data in plan.news_analysis.get('symbol_scores', []):
            symbol = score_data.get('symbol')
            if symbol:
                news_scores[symbol] = score_data

    # Show market context if available
    if market_context:
        lines.append(f"_{market_context}_")
        lines.append("")

    # Process each stock with unified scoring
    for rec in recommendations[:6]:  # Limit to first 6 for readability
        symbol = rec.symbol if hasattr(rec, 'symbol') else rec.get('symbol')
        if not symbol:
            continue

        # Get technical analysis
        tech_score = tech_scores.get(symbol)
        tech_rationale = ""
        tech_risk = ""
        if tech_score:
            tech_rationale = getattr(tech_score, 'rationale', '')
            tech_risk = getattr(tech_score, 'risk_note', '')

        # Get news analysis
        news_data = news_scores.get(symbol)
        news_content = []

        # Calculate unified score (favor technical analysis, adjust with news sentiment)
        base_score = getattr(tech_score, 'score', 5) if tech_score else 5

        # Adjust based on news sentiment if available
        final_score = base_score
        if news_data:
            buy_potential = news_data.get('buy_potential_score', 50)
            confidence = news_data.get('confidence', 0.5)

            # Convert 0-100 news score to -2 to +2 adjustment
            news_adjustment = ((buy_potential - 50) / 25) * confidence
            final_score = max(1, min(10, int(base_score + news_adjustment)))

            # Get news insights (remove IDs and show more text)
            bull_points = news_data.get('key_bull_points', [])
            risk_points = news_data.get('key_risks', [])

            # Clean up news content - remove ID references and show full text
            for point in bull_points[:2]:  # Limit to 2 key points
                # Remove ID references like "(ID: abc123)"
                clean_point = re.sub(r'\s*\(ID:\s*[^)]+\)', '', point.strip())
                if clean_point and len(clean_point) > 10:
                    news_content.append(f"📈 {clean_point}")

            for point in risk_points[:1]:  # Limit to 1 risk point
                clean_point = re.sub(r'\s*\(ID:\s*[^)]+\)', '', point.strip())
                if clean_point and len(clean_point) > 10:
                    news_content.append(f"⚠ {clean_point}")

        # Score indicator
        if final_score >= 8:
            indicator = "🟢"
        elif final_score >= 6:
            indicator = "🔵"
        elif final_score >= 4:
            indicator = "🟡"
        else:
            indicator = "🔴"

        # Format unified analysis for this stock
        lines.append(f"  `{symbol}` {indicator} {final_score}/10")

        # Technical insights
        if tech_rationale:
            lines.append(f"    📊 Technical: {tech_rationale}")

        # News insights (more text, no IDs)
        for news_line in news_content:
            lines.append(f"    {news_line}")

        # Combined risk assessment (avoid duplication with news risks)
        if tech_risk and not any("⚠" in line for line in news_content):
            lines.append(f"    ⚠ Risk: {tech_risk}")

        lines.append("")  # Space between stocks

    # Remove extra blank line at end
    if lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)


def format_weekly_digest(
    plan: WeeklyPlan,
    portfolio_state: PortfolioState,
    guardrails: GuardrailsReport | None,
    ai_analysis: AIAnalysis | None = None,
) -> str:
    """Format the weekly digest Telegram message."""
    total = portfolio_state.total_value

    # Add market regime indicator
    regime_emoji = {"bull": "🐂", "bear": "🐻", "sideways": "🦀"}.get(plan.market_regime, "📊")
    regime_text = f" — {regime_emoji} {plan.market_regime.upper()}" if plan.market_regime else ""

    lines = [
        f"📊 *Weekly Plan — S1 v{plan.strategy_version}*{regime_text}",
        f"📅 {plan.generated_at[:10]}  💰 {total:,.0f} ₫",
        "",
    ]

    buys = [r for r in plan.recommendations if r.action == "BUY"][:10]
    if buys:
        lines.append(f"*🟢 BUY Signals ({len(buys)})*")
        lines.append("")
        for r in buys:
            icon = _ENTRY_ICON.get(r.entry_type, "·")
            vnd = _alloc_vnd(r.position_target_pct, total) if r.position_target_pct and total else 0
            alloc_str = f" — {vnd:,.0f} ₫" if vnd else ""
            lines.append(f"  📈 `{r.symbol}` {icon} {r.entry_type.capitalize()}{alloc_str}")
            lines.append(f"    🎯 Entry: {r.entry_price:,.0f}")
            lines.append(f"    📊 Zone: {r.buy_zone_low:,.0f}–{r.buy_zone_high:,.0f}")
            lines.append(f"    🛡️ SL {r.stop_loss:,.0f} | TP {r.take_profit:,.0f}")
            lines.append("")

    # Simplified - treat all held positions the same
    holds = [r for r in plan.recommendations if r.action in ("HOLD", "REDUCE", "SELL")]
    if holds:
        lines.append("*📋 Open Positions — Alert Monitoring*")
        lines.append("")

        # Load current prices for better context
        cached = _load_cached_prices([r.symbol for r in holds])

        for r in holds:

            # Show current price + P&L if available
            current = cached.get(r.symbol)
            if current and r.entry_price and r.entry_price > 0:
                pnl_pct = ((current - r.entry_price) / r.entry_price) * 100
                status_line = f"  📊 `{r.symbol}` @ {current:,.0f} ({pnl_pct:+.1f}%)"
            else:
                status_line = f"  📊 `{r.symbol}` Monitoring"

            lines.append(status_line)

            # Clean exit alert format
            tp_str = f"TP {r.take_profit:,.0f}" if r.take_profit else ""
            sl_str = f"SL {r.stop_loss:,.0f}" if r.stop_loss else ""
            exit_levels = " | ".join(filter(None, [sl_str, tp_str]))

            lines.append(f"    🔔 Exit alerts: {exit_levels}")
            lines.append("")  # Spacing between positions

        # Remove extra line at end
        if lines and lines[-1] == "":
            lines.pop()

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

    # Only show guardrails when there are meaningful warnings
    if guardrails and guardrails.recommendations and len(guardrails.recommendations) > 0:
        # Filter out trivial strategy switch recommendations (e.g., -0.00% differences)
        meaningful_recs = []
        for rec in guardrails.recommendations:
            if "SWITCH_STRATEGY" in rec and "-0.0" in rec:
                # Skip trivial strategy switch recommendations near zero
                continue
            meaningful_recs.append(rec)

        if meaningful_recs:
            lines.append("")
            lines.append("*⚠️ Alerts*")
            for rec in meaningful_recs:
                lines.append(f"  {rec}")

    # Unified Market Analysis (Technical + News)
    if ai_analysis or (hasattr(plan, 'news_analysis') and plan.news_analysis):
        unified_section = _format_unified_analysis(ai_analysis, plan, plan.recommendations)
        if unified_section:
            lines.append(unified_section)

    return "\n".join(lines)


def format_alert(alert: Alert, portfolio_state: PortfolioState | None = None) -> str:
    """Format price alert with clear action guidance."""

    if alert.alert_type == "STOP_LOSS_HIT":
        lines = [
            f"🔴 **STOP LOSS HIT**",
            f"`{alert.symbol}` — Price hit {alert.current_price:,.0f}",
            f"💡 *SL threshold: {alert.threshold:,.0f}*"
        ]

        # Add helpful P&L context
        if portfolio_state and alert.symbol in portfolio_state.positions:
            pos = portfolio_state.positions[alert.symbol]
            pnl_pct = ((alert.current_price - pos.avg_cost) / pos.avg_cost) * 100
            pnl_vnd = (alert.current_price - pos.avg_cost) * pos.qty

            lines.extend([
                "",
                f"📈 **Trade Summary:**",
                f"Entry: {pos.avg_cost:,.0f} → Current: {alert.current_price:,.0f}",
                f"P&L: {pnl_pct:+.1f}% ({pnl_vnd:+,.0f} ₫)"
            ])

        return "\n".join(lines)

    if alert.alert_type == "TAKE_PROFIT_HIT":
        lines = [
            f"🟢 **TAKE PROFIT HIT**",
            f"`{alert.symbol}` — Price hit {alert.current_price:,.0f}",
            f"🎯 *TP threshold: {alert.threshold:,.0f}*"
        ]

        if portfolio_state and alert.symbol in portfolio_state.positions:
            pos = portfolio_state.positions[alert.symbol]
            pnl_pct = ((alert.current_price - pos.avg_cost) / pos.avg_cost) * 100
            pnl_vnd = (alert.current_price - pos.avg_cost) * pos.qty

            lines.extend([
                "",
                f"📈 **Trade Summary:**",
                f"Entry: {pos.avg_cost:,.0f} → Current: {alert.current_price:,.0f}",
                f"P&L: +{pnl_pct:.1f}% (+{pnl_vnd:,.0f} ₫)"
            ])

        return "\n".join(lines)

    if alert.alert_type == "ENTERED_BUY_ZONE":
        return (
            f"🔵 **BUY ZONE ENTRY**\n"
            f"`{alert.symbol}` — Entered buy zone\n"
            f"💡 *Current: {alert.current_price:,.0f} | Zone: ≥ {alert.threshold:,.0f}*\n"
            f"\n"
            f"📋 Check /plan for entry details"
        )

    # Fallback
    return f"🔔 **{alert.alert_type}** `{alert.symbol}`: {alert.current_price:,.0f}"


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
        lines.append(f"*🟢 BUY Signals ({len(buys)})*")
        lines.append("")
        for r in buys:
            sym = r["symbol"]
            icon = _ENTRY_ICON.get(r.get("entry_type", ""), "·")
            entry = r.get("entry_price", 0)
            pct = r.get("position_target_pct", 0)
            vnd = _alloc_vnd(pct, total_value) if pct and total_value else 0
            alloc_str = f" — {vnd:,.0f} ₫" if vnd else ""

            lines.append(f"  📈 `{sym}` {icon} {r.get('entry_type','').capitalize()}{alloc_str}")

            now = cached.get(sym)
            if now:
                label = _zone_label(now, r.get("buy_zone_low", 0), r.get("buy_zone_high", 0))
                lines.append(f"    📊 Now {now:,.0f}  {label}")

            lines.append(f"    🎯 Entry: {entry:,.0f}")
            lines.append(f"    📊 Zone: {r.get('buy_zone_low', 0):,.0f}–{r.get('buy_zone_high', 0):,.0f}")
            lines.append(f"    🛡️ SL {r.get('stop_loss', 0):,.0f} | TP {r.get('take_profit', 0):,.0f}")
            lines.append("")

    if others:
        lines.append("")
        lines.append("*📋 Open Positions — Alert Monitoring*")
        lines.append("")

        for r in others:
            sym = r["symbol"]

            # Show current price if available
            now = cached.get(sym)
            if now and r.get("entry_price", 0) > 0:
                pnl_pct = ((now - r["entry_price"]) / r["entry_price"]) * 100
                status_line = f"  📊 `{sym}` @ {now:,.0f} ({pnl_pct:+.1f}%)"
            else:
                now_str = f" — now {now:,.0f}" if now else ""
                status_line = f"  📊 `{sym}` Monitoring{now_str}"

            lines.append(status_line)

            # Exit levels
            tp = r.get("take_profit", 0)
            sl = r.get("stop_loss", 0)
            tp_str = f"TP {tp:,.0f}" if tp else ""
            sl_str = f"SL {sl:,.0f}" if sl else ""
            exit_levels = " | ".join(filter(None, [sl_str, tp_str]))

            lines.append(f"    🔔 Exit alerts: {exit_levels}")
            lines.append("")

    # Add cached AI analysis section if available
    ai_analysis = plan_data.get("ai_analysis")
    if ai_analysis:
        lines.append("")
        lines.append("*🤖 AI Analysis*")

        # Market context
        if ai_analysis.get("market_context"):
            lines.append(f"_{ai_analysis['market_context']}_")
            lines.append("")

        if ai_analysis.get("generated"):
            # Normal AI analysis with scores
            ai_scores = ai_analysis.get("scores", {})
            for r in recs[:5]:  # Limit to first 5 recommendations
                sym = r["symbol"]
                ai_score = ai_scores.get(sym)
                if ai_score:
                    score = ai_score.get("score", 5)
                    rationale = ai_score.get("rationale", "")
                    risk_note = ai_score.get("risk_note", "")

                    # Score bar
                    if score >= 8:
                        bar = "🟢"
                    elif score >= 6:
                        bar = "🔵"
                    elif score >= 4:
                        bar = "🟡"
                    else:
                        bar = "🔴"

                    lines.append(f"  `{sym}` {bar} {score}/10")
                    if rationale:
                        lines.append(f"    {rationale}")
                    if risk_note:
                        lines.append(f"    ⚠ {risk_note}")
        else:
            # Rate limit or API not configured notice
            if ai_analysis.get("notice"):
                lines.append(f"{ai_analysis['notice']}")
            lines.append("")

    return "\n".join(lines)
