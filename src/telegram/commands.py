"""Telegram command parsers — /buy, /sell, /setcash, /status, /plan, /help."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from src.models import TradeRecord
from src.portfolio.engine import append_trade, get_portfolio_state, load_trades
from src.telegram.formatter import format_plan_summary, format_status
from src.utils.csv_safety import parse_number, validate_symbol

logger = logging.getLogger(__name__)


def handle_command(text: str) -> str:
    """Route a command string to the appropriate handler.

    Returns the response message string.
    """
    text = text.strip()
    parts = text.split(None, 1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    handlers = {
        "/buy": lambda: _handle_trade(args, side="BUY"),
        "/sell": lambda: _handle_trade(args, side="SELL"),
        "/setcash": lambda: _handle_setcash(args),
        "/status": lambda: _handle_status(),
        "/plan": lambda: _handle_plan(),
        "/help": lambda: _handle_help(),
    }

    handler = handlers.get(cmd)
    if handler is None:
        return f"Unknown command: {cmd}\nType /help for available commands."

    try:
        return handler()
    except Exception as e:
        logger.error("Command error for '%s': %s", text, e)
        return f"Error: {e}"


def _handle_trade(args: str, side: str) -> str:
    """Parse and execute /buy or /sell command.

    Format: SYMBOL QTY PRICE [asset=stock|bond|fund] [fee=NUMBER] [note=TEXT]
    """
    if not args:
        return f"Usage: /{side.lower()} SYMBOL QTY PRICE [asset=stock|bond|fund] [fee=N] [note=TEXT]"

    tokens = args.split()
    if len(tokens) < 3:
        return f"Usage: /{side.lower()} SYMBOL QTY PRICE [asset=stock|bond|fund] [fee=N] [note=TEXT]"

    try:
        symbol = validate_symbol(tokens[0])
        qty = parse_number(tokens[1])
        price = parse_number(tokens[2])
    except ValueError as e:
        return f"Parse error: {e}"

    if qty <= 0:
        return "Error: qty must be positive"
    if price <= 0:
        return "Error: price must be positive"

    # Parse optional key=value params
    asset_class = "stock"
    fee = 0.0
    note = ""
    for token in tokens[3:]:
        if "=" in token:
            key, val = token.split("=", 1)
            key = key.lower()
            if key == "asset":
                if val.lower() not in ("stock", "bond", "fund"):
                    return f"Error: asset must be stock, bond, or fund (got '{val}')"
                asset_class = val.lower()
            elif key == "fee":
                try:
                    fee = parse_number(val)
                except ValueError:
                    return f"Error: invalid fee value '{val}'"
            elif key == "note":
                note = val
        else:
            note = (note + " " + token).strip() if note else token

    trade = TradeRecord(
        timestamp_iso=datetime.utcnow().isoformat(),
        asset_class=asset_class,
        symbol=symbol,
        side=side,
        qty=qty,
        price=price,
        fee=fee,
        note=note,
    )
    append_trade(trade)

    total = price * qty + (fee if side == "BUY" else -fee)
    return (
        f"Recorded {side} {symbol}\n"
        f"Qty: {qty:,.0f} @ {price:,.0f}\n"
        f"Asset: {asset_class} | Fee: {fee:,.0f}\n"
        f"Total: {total:,.0f}"
    )


def _handle_setcash(args: str) -> str:
    """Parse /setcash AMOUNT."""
    if not args:
        return "Usage: /setcash AMOUNT"

    try:
        amount = parse_number(args.strip())
    except ValueError as e:
        return f"Parse error: {e}"

    if amount < 0:
        return "Error: cash amount cannot be negative"

    trade = TradeRecord(
        timestamp_iso=datetime.utcnow().isoformat(),
        asset_class="fund",
        symbol="CASH",
        side="CASH",
        qty=1,
        price=amount,
        fee=0,
        note="setcash",
    )
    append_trade(trade)
    return f"Cash balance set to {amount:,.0f}"


def _handle_status() -> str:
    """Return portfolio status."""
    state = get_portfolio_state()
    return format_status(state)


def _handle_plan() -> str:
    """Return current weekly plan summary."""
    plan_path = Path("data/weekly_plan.json")
    if not plan_path.exists():
        return "No weekly plan generated yet. Run the weekly workflow first."
    try:
        with open(plan_path) as f:
            plan_data = json.load(f)
        return format_plan_summary(plan_data)
    except Exception as e:
        return f"Error loading plan: {e}"


def _handle_help() -> str:
    return (
        "*Available Commands*\n\n"
        "`/buy SYMBOL QTY PRICE` — Record a buy trade\n"
        "  Options: `asset=stock|bond|fund` `fee=N` `note=TEXT`\n\n"
        "`/sell SYMBOL QTY PRICE` — Record a sell trade\n"
        "  Options: `asset=stock|bond|fund` `fee=N` `note=TEXT`\n\n"
        "`/setcash AMOUNT` — Set cash balance\n\n"
        "`/status` — View portfolio positions & allocation\n\n"
        "`/plan` — View current weekly plan\n\n"
        "`/help` — Show this message"
    )
