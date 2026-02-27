"""Telegram bot — long-poll getUpdates, command routing, admin gate."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import requests

from src.telegram.commands import handle_command

logger = logging.getLogger(__name__)

BOT_STATE_PATH = "data/bot_state.json"


class TelegramBot:
    def __init__(
        self,
        token: str | None = None,
        admin_chat_id: str | None = None,
    ):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "8620394249:AAEe209BkfQ_VaCBkhq6Xq0X34AWFxSX4LQ")
        self.admin_chat_id = str(
            admin_chat_id or os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "6226624607")
        )
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self._session = requests.Session()

        if not self.token:
            logger.warning("TELEGRAM_BOT_TOKEN not set — bot will not function")

    def get_updates(self, offset: int = 0, timeout: int = 30) -> list[dict]:
        """Long-poll Telegram for new updates."""
        try:
            resp = self._session.get(
                f"{self.base_url}/getUpdates",
                params={"offset": offset, "timeout": timeout},
                timeout=timeout + 10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("ok"):
                return data.get("result", [])
            logger.warning("getUpdates not ok: %s", data)
            return []
        except Exception as e:
            logger.error("getUpdates failed: %s", e)
            return []

    def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "Markdown",
    ) -> bool:
        """Send a message via Telegram API."""
        if not self.token:
            logger.warning("No bot token — message not sent: %s", text[:80])
            return False
        try:
            # Telegram has a 4096 char limit per message
            for chunk in _chunk_message(text, 4000):
                resp = self._session.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": chunk,
                        "parse_mode": parse_mode,
                    },
                    timeout=15,
                )
                if not resp.json().get("ok"):
                    # Retry without parse_mode if markdown fails
                    resp = self._session.post(
                        f"{self.base_url}/sendMessage",
                        json={"chat_id": chat_id, "text": chunk},
                        timeout=15,
                    )
            return True
        except Exception as e:
            logger.error("sendMessage failed: %s", e)
            return False

    def send_admin(self, text: str) -> bool:
        """Send a message to the admin chat."""
        return self.send_message(self.admin_chat_id, text)

    def run_once(self) -> bool:
        """Single poll cycle for cron usage.

        Returns True if any updates were processed (state changed).
        """
        state = _load_bot_state()
        last_id = state.get("last_update_id", 0)

        updates = self.get_updates(offset=last_id + 1, timeout=5)
        if not updates:
            logger.info("No new updates")
            return False

        state_changed = False
        for update in updates:
            update_id = update.get("update_id", 0)
            if update_id <= last_id:
                continue

            message = update.get("message", {})
            chat_id = str(message.get("chat", {}).get("id", ""))
            text = message.get("text", "")

            if chat_id != self.admin_chat_id:
                logger.warning(
                    "Ignoring message from non-admin chat: %s (expected: %s, message: %s)",
                    chat_id,
                    self.admin_chat_id,
                    text[:50],
                )
                state["last_update_id"] = update_id
                state_changed = True
                continue

            if text.startswith("/"):
                response = handle_command(text)
                self.send_message(chat_id, response)

            state["last_update_id"] = update_id
            state_changed = True

        if state_changed:
            _save_bot_state(state)

        return state_changed

    def run_continuous(self, poll_interval: int = 5) -> None:
        """Continuously poll for updates and process commands.

        This runs indefinitely until interrupted.
        """
        logger.info("Starting continuous bot polling (interval: %ds)", poll_interval)
        try:
            while True:
                self.run_once()
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            logger.info("Bot polling stopped")


def _load_bot_state() -> dict:
    p = Path(BOT_STATE_PATH)
    if p.exists():
        try:
            with open(p) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"last_update_id": 0}


def _save_bot_state(state: dict) -> None:
    p = Path(BOT_STATE_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(state, f, indent=2)


def _chunk_message(text: str, max_len: int = 4000) -> list[str]:
    """Split a long message into chunks."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Find a good split point
        split = text.rfind("\n", 0, max_len)
        if split <= 0:
            split = max_len
        chunks.append(text[:split])
        text = text[split:].lstrip("\n")
    return chunks
