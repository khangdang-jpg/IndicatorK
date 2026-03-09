"""Standalone AI analysis sender — triggered after weekly plan workflow completes.

Reads pre-computed AI + news results from data/weekly_plan.json and sends
a standalone Telegram message with technical analysis, news analysis, and
summary scores per stock.

Toggle off: set GitHub repo variable AI_ANALYSIS_ENABLED=false
"""

import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

from src.utils.logging_setup import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging()

    # Toggle: skip if explicitly disabled
    enabled = os.environ.get("AI_ANALYSIS_ENABLED", "false").strip().lower()
    if enabled == "false":
        logger.info("AI_ANALYSIS_ENABLED=false — skipping AI analysis message")
        return

    # Load weekly plan with cached AI + news data
    plan_path = Path("data/weekly_plan.json")
    if not plan_path.exists():
        logger.warning("weekly_plan.json not found — skipping AI analysis message")
        return

    try:
        with open(plan_path) as f:
            plan_data = json.load(f)
    except Exception as e:
        logger.error("Failed to load weekly_plan.json: %s", e)
        return

    ai_dict = plan_data.get("ai_analysis")
    news_dict = plan_data.get("news_analysis")

    # Pre-check: skip early if there is nothing meaningful to send
    has_tech = bool(ai_dict and ai_dict.get("generated", False) and ai_dict.get("scores"))
    has_news = bool(news_dict and news_dict.get("symbol_scores"))
    if not has_tech and not has_news:
        logger.info("No meaningful AI or news data in weekly_plan.json — skipping")
        return

    # Reconstruct WeeklyPlan model
    from src.models import WeeklyPlan
    plan = WeeklyPlan.from_dict(plan_data)

    # Reconstruct AIAnalysis using the canonical from_dict() classmethod
    from src.ai.groq_analyzer import AIAnalysis
    ai_analysis = AIAnalysis.from_dict(ai_dict) if ai_dict else None

    # Format and send
    from src.telegram.formatter import format_ai_analysis_message
    from src.telegram.bot import TelegramBot

    message = format_ai_analysis_message(plan, ai_analysis)
    if not message:
        logger.info("format_ai_analysis_message returned empty — nothing to send")
        return

    bot = TelegramBot()
    bot.send_admin(message)
    logger.info("AI analysis message sent")


if __name__ == "__main__":
    main()
