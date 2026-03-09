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
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path


def _json_2dp(obj: dict) -> str:
    """Serialize to JSON ensuring every float value has exactly 2 decimal places.

    Python's json module outputs 70.0 for round(70.0, 2) and 0 for integer
    zeros — both wrong for price fields.  This post-processes the raw JSON
    string while correctly skipping float literals inside quoted strings.
    """
    raw = json.dumps(obj, indent=2)
    _single_dp = re.compile(r"-?\d+\.\d(?!\d)")
    result: list[str] = []
    in_string = False
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == '"' and (i == 0 or raw[i - 1] != "\\"):
            in_string = not in_string
            result.append(c)
            i += 1
        elif not in_string:
            m = _single_dp.match(raw, i)
            if m:
                result.append(m.group(0) + "0")
                i = m.end()
            else:
                result.append(c)
                i += 1
        else:
            result.append(c)
            i += 1
    return "".join(result)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load environment variables from .env file (for local execution)
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Loaded environment from {env_path}")
    else:
        print("ℹ️  No .env file found - using system environment variables")
except ImportError:
    # python-dotenv not installed - OK on GitHub Actions where env vars are set directly
    print("ℹ️  python-dotenv not available - using system environment variables")

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

    # Idempotency check - prevent double processing on GitHub Actions retry
    run_id = os.environ.get("GITHUB_RUN_ID")
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")

    if run_id:
        # Use separate file for idempotency tracking - don't modify portfolio state
        if _is_run_already_processed(run_id):
            logger.info(f"Run {run_id} already processed, skipping execution")
            return
        logger.info(f"Processing GitHub Actions run {run_id} (attempt {run_attempt})")

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
    from src.ai.groq_analyzer import analyze_weekly_plan, is_available as ai_available
    from datetime import datetime
    ai_analysis = None
    if ai_available():
        logger.info("Running Groq AI analysis...")
        portfolio_summary = (
            f"Total: {portfolio_state.total_value:,.0f} VND | "
            f"Cash: {portfolio_state.cash:,.0f} | "
            f"Positions: {len(portfolio_state.positions)} | "
            f"Unrealized PnL: {portfolio_state.unrealized_pnl:+,.0f}"
        )
        as_of_ts = datetime.utcnow().isoformat()
        ai_analysis = analyze_weekly_plan(plan.to_dict(), portfolio_summary, as_of=as_of_ts)
        if ai_analysis.generated:
            logger.info("AI analysis complete: %d scores", len(ai_analysis.scores))
            # Convert AIAnalysis to dict for caching (compatible with Cloudflare Workers format)
            ai_dict = {
                "generated": ai_analysis.generated,
                "market_context": ai_analysis.market_context,
                "analysis_date": datetime.now().strftime("%Y-%m-%d"),
                "data_sources": "Weekly technical analysis using Groq AI",
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
            logger.warning("🚨 AI analysis returned empty — continuing without it")
            logger.warning("📊 Weekly plan generated successfully without AI scoring")
    else:
        logger.warning("Groq AI not available")

    # News-based buy potential scoring (after AI analysis)
    try:
        from src.news_ai import score_buy_potential, fetch_recent_news
        logger.info("Running news-based buy potential analysis...")

        # Fetch real news about Vietnamese stocks (returns dict: symbol -> [news])
        logger.info("Fetching real news about Vietnamese stock symbols...")
        try:
            symbol_news = fetch_recent_news(
                symbols=all_symbols[:10],  # Fetch for top 10 symbols to manage API limits
                days_back=7,
                use_cache=True,
            )
            total_articles = sum(len(articles) for articles in symbol_news.values())
            logger.info(f"Fetched news for {len(symbol_news)} symbols ({total_articles} articles total)")
        except Exception as e:
            logger.warning(f"Failed to fetch real news: {e}, using fallback")
            symbol_news = {}  # Empty dict triggers fallback in scorer

        # Save plan temporarily for buy potential scoring
        temp_plan_path = "data/weekly_plan_temp.json"
        plan_dict = plan.to_dict()
        with open(temp_plan_path, "w") as f:
            json.dump(plan_dict, f, indent=2)

        # Score buy potential with per-symbol news
        # Pass symbol_news dict directly with symbol-to-articles mapping preserved
        logger.info(f"Scoring {len(symbol_news)} symbols with pre-matched news articles")

        news_scores = score_buy_potential(temp_plan_path, symbol_news)

        if news_scores.get("status") == "SUCCESS":
            logger.info("News analysis complete: %d symbols scored", news_scores.get("analyzed_symbols", 0))
            # Save news scores
            Path("data/news_scores.json").write_text(json.dumps(news_scores, indent=2))

            # Add news scores to plan
            plan.news_analysis = news_scores
        else:
            logger.warning("News analysis failed: %s", news_scores.get("status"))

        # Clean up temp file
        if Path(temp_plan_path).exists():
            Path(temp_plan_path).unlink()

    except Exception as e:
        logger.warning("News analysis failed: %s", e)
    # Write weekly plan (now includes AI analysis if available)
    plan_path = Path("data/weekly_plan.json")
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(_json_2dp(plan.to_dict()))

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

    # Send weekly digest via Telegram (no AI section — sent separately by ai_analysis workflow)
    bot = TelegramBot()
    digest = format_weekly_digest(plan, portfolio_state, guardrails_report, include_analysis=False)
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

    # Mark GitHub Actions run as processed (for idempotency)
    if run_id:
        _mark_run_processed(run_id)
        logger.info(f"Marked run {run_id} as processed")

    logger.info("Weekly workflow complete")


def _is_run_already_processed(run_id: str) -> bool:
    """Check if GitHub Actions run was already processed (separate from portfolio state)."""
    idempotency_file = Path("data/weekly_runs_processed.json")
    if not idempotency_file.exists():
        return False

    try:
        with open(idempotency_file, 'r') as f:
            processed_runs = json.load(f)
        return run_id in processed_runs.get('runs', [])
    except (json.JSONDecodeError, KeyError):
        return False


def _mark_run_processed(run_id: str) -> None:
    """Mark GitHub Actions run as processed (separate from portfolio state)."""
    idempotency_file = Path("data/weekly_runs_processed.json")

    # Load existing data
    if idempotency_file.exists():
        try:
            with open(idempotency_file, 'r') as f:
                data = json.load(f)
        except (json.JSONDecodeError, KeyError):
            data = {"runs": []}
    else:
        data = {"runs": []}

    # Add run_id if not already present
    if run_id not in data['runs']:
        data['runs'].append(run_id)
        # Keep only last 50 runs to prevent file bloat
        data['runs'] = data['runs'][-50:]

        # Write back
        idempotency_file.parent.mkdir(parents=True, exist_ok=True)
        with open(idempotency_file, 'w') as f:
            json.dump(data, f, indent=2)


if __name__ == "__main__":
    main()
