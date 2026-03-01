"""Entry point: weekly plan generation workflow.

Steps:
  1. Fetch daily history for all watchlist + held symbols
  2. Compute portfolio state
  3. Generate weekly plan via active strategy
  4. Run guardrails
  5. (Optional) AI analysis via Gemini
  6. Append portfolio snapshot
  7. Send weekly digest via Telegram
  8. Persist cache to disk (once per week)
"""

import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.guardrails.engine import run_guardrails, save_guardrails_report
from src.portfolio.engine import (
    append_portfolio_snapshot,
    get_portfolio_state,
    load_portfolio_snapshots,
)
from src.telegram.bot import TelegramBot
from src.telegram.formatter import format_weekly_digest
from src.utils.config import get_provider, get_risk_config, get_strategy, load_watchlist
from src.utils.logging_setup import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging()
    logger.info("Starting weekly plan generation")

    # Load config
    provider = get_provider()
    strategy = get_strategy()
    risk_config = get_risk_config()
    watchlist = load_watchlist()

    # Get portfolio state to know held symbols
    portfolio_state = get_portfolio_state()
    held_symbols = list(portfolio_state.positions.keys())

    # Combine watchlist + held symbols (no dupes)
    all_symbols = list(dict.fromkeys(watchlist + held_symbols))
    logger.info("Universe: %d symbols (%d watchlist + %d held)", len(all_symbols), len(watchlist), len(held_symbols))

    # Fetch daily history (last 52 weeks)
    end = date.today()
    start = end - timedelta(weeks=52)
    market_data = {}
    for sym in all_symbols:
        history = provider.get_daily_history(sym, start, end)
        if history:
            market_data[sym] = history
            logger.info("Fetched %d candles for %s", len(history), sym)
        else:
            logger.warning("No history for %s", sym)

    # Update portfolio with current prices
    current_prices = {
        sym: candles[-1].close
        for sym, candles in market_data.items()
        if candles
    }
    portfolio_state = get_portfolio_state(current_prices=current_prices)

    # Generate weekly plan
    plan = strategy.generate_weekly_plan(market_data, portfolio_state, risk_config)
    logger.info("Generated plan with %d recommendations", len(plan.recommendations))

    # AI analysis (run BEFORE saving plan so we can cache the results)
    from src.ai.gemini_analyzer import analyze_weekly_plan, is_available as ai_available
    ai_analysis = None
    if ai_available():
        logger.info("Running Gemini AI analysis...")
        portfolio_summary = (
            f"Total: {portfolio_state.total_value:,.0f} VND | "
            f"Cash: {portfolio_state.cash:,.0f} | "
            f"Positions: {len(portfolio_state.positions)} | "
            f"Unrealized PnL: {portfolio_state.unrealized_pnl:+,.0f}"
        )
        ai_analysis = analyze_weekly_plan(plan.to_dict(), portfolio_summary)
        if ai_analysis.generated:
            logger.info("AI analysis complete: %d scores", len(ai_analysis.scores))
            # Convert AIAnalysis to dict for caching (compatible with Cloudflare Workers format)
            from datetime import datetime
            ai_dict = {
                "generated": ai_analysis.generated,
                "market_context": ai_analysis.market_context,
                "analysis_date": datetime.now().strftime("%Y-%m-%d"),
                "data_sources": "Weekly technical analysis using Gemini AI",
                "scores": {
                    sym: {
                        "symbol": score.symbol,
                        "score": score.score,
                        "rationale": score.rationale,
                        "risk_note": score.risk_note
                    }
                    for sym, score in ai_analysis.scores.items()
                }
            }
            plan.ai_analysis = ai_dict
        else:
            logger.warning("AI analysis returned empty — continuing without it")
    else:
        logger.info("Gemini API not configured — skipping AI analysis")

    # Write weekly plan (now includes AI analysis if available)
    plan_path = Path("data/weekly_plan.json")
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    with open(plan_path, "w") as f:
        json.dump(plan.to_dict(), f, indent=2)

    # Run guardrails
    snapshots = load_portfolio_snapshots()
    provider_health = provider.get_health_stats()
    guardrails_report = run_guardrails(
        provider_health=provider_health,
        strategy_id=strategy.id,
        portfolio_state=portfolio_state,
        snapshots=snapshots,
        risk_config=risk_config,
    )
    save_guardrails_report(guardrails_report)

    # Append portfolio snapshot (weekly tracking)
    append_portfolio_snapshot(portfolio_state)
    logger.info("Portfolio snapshot appended")

    # Persist cache to disk (once per week)
    provider.save_cache()
    logger.info("Price cache persisted")

    # Send weekly digest via Telegram
    bot = TelegramBot()
    # Convert cached AI analysis back to AIAnalysis object for digest formatting
    digest_ai_analysis = ai_analysis  # Use original AIAnalysis object if available
    if ai_analysis is None and plan.ai_analysis:
        # If we only have cached data, reconstruct AIAnalysis object
        from src.ai.gemini_analyzer import AIAnalysis, AIScore
        cached_ai = plan.ai_analysis
        scores = {}
        for sym, score_data in cached_ai.get("scores", {}).items():
            scores[sym] = AIScore(
                symbol=score_data["symbol"],
                score=score_data["score"],
                rationale=score_data["rationale"],
                risk_note=score_data["risk_note"]
            )
        digest_ai_analysis = AIAnalysis(
            scores=scores,
            market_context=cached_ai.get("market_context", ""),
            generated=cached_ai.get("generated", False)
        )

    digest = format_weekly_digest(plan, portfolio_state, guardrails_report, digest_ai_analysis)
    bot.send_admin(digest)
    logger.info("Weekly digest sent")

    # GitHub Actions job summary
    summary_path = Path(
        __import__("os").environ.get("GITHUB_STEP_SUMMARY", "/dev/null")
    )
    try:
        with open(summary_path, "a") as f:
            f.write(f"## Weekly Plan — {strategy.id} v{strategy.version}\n")
            f.write(f"- Recommendations: {len(plan.recommendations)}\n")
            f.write(f"- Portfolio value: {portfolio_state.total_value:,.0f}\n")
            if guardrails_report.recommendations:
                f.write("- **Guardrail warnings:**\n")
                for rec in guardrails_report.recommendations:
                    f.write(f"  - {rec}\n")
    except OSError:
        pass

    logger.info("Weekly workflow complete")


if __name__ == "__main__":
    main()
