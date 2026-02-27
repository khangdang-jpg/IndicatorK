"""Entry point: Telegram bot poll — process commands.

Runs 24/7 (no trading-hours gate) so commands work anytime.
Only commits state if something actually changed.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.config import _load_env_file
from src.telegram.bot import TelegramBot
from src.utils.logging_setup import setup_logging

_load_env_file()

logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging()
    logger.info("Starting bot poll")

    bot = TelegramBot()
    if not bot.token:
        logger.error("TELEGRAM_BOT_TOKEN not set — exiting")
        return

    # Run once for GitHub Actions cron execution (not continuously)
    bot.run_once()


if __name__ == "__main__":
    main()
