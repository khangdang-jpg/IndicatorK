"""Entry point: alerts workflow — check prices and send alerts.

Exit codes:
  0 — success (alerts sent or no alerts needed)
  0 — outside trading hours (early exit, no network calls)
"""

import json
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import WeeklyPlan
from src.telegram.alerts import check_alerts, load_alerts_state, save_alerts_state
from src.telegram.bot import TelegramBot
from src.telegram.formatter import format_alert
from src.utils.config import get_provider, load_watchlist
from src.utils.logging_setup import setup_logging
from src.utils.trading_hours import is_trading_hours

logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging()

    # Trading hours gate — exit before any network calls
    if not is_trading_hours():
        logger.info("Outside Vietnam trading hours — exiting early")
        return

    # Load weekly plan
    plan_path = Path("data/weekly_plan.json")
    if not plan_path.exists():
        logger.warning("No weekly plan found — nothing to check")
        return

    with open(plan_path) as f:
        plan = WeeklyPlan.from_dict(json.load(f))

    if not plan.recommendations:
        logger.info("No recommendations in plan — nothing to check")
        return

    # Get symbols to check (from plan + watchlist)
    symbols = list({r.symbol for r in plan.recommendations})

    # Fetch current prices
    provider = get_provider()
    current_prices = provider.get_last_prices(symbols)

    if not current_prices:
        logger.warning("No prices fetched — skipping alert check")
        return

    logger.info("Fetched prices for %d/%d symbols", len(current_prices), len(symbols))

    # Check alerts with dedup
    alerts_state = load_alerts_state()
    alerts, updated_state, state_changed = check_alerts(
        plan, current_prices, alerts_state
    )

    # Send alerts via Telegram
    if alerts:
        bot = TelegramBot()
        for alert in alerts:
            msg = format_alert(alert)
            bot.send_admin(msg)
            logger.info("Alert sent: %s", alert.message)

    # Only save state if it changed
    if state_changed:
        save_alerts_state(updated_state)
        logger.info("Alerts state updated")

    # Update in-memory cache (NOT persisted to disk here — see weekly workflow)
    # provider.save_cache() is intentionally NOT called during 5-min runs

    logger.info("Alerts check complete: %d alerts sent", len(alerts))


if __name__ == "__main__":
    main()
