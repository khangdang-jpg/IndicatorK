"""One-time alert checker functions for position-aware alerting."""

from __future__ import annotations

import logging
from datetime import datetime

from src.models import Alert

logger = logging.getLogger(__name__)


def check_zone_once(
    state: dict,
    symbol: str,
    alert_type: str,
    price: float,
    low: float,
    high: float,
    now: datetime,
) -> tuple[Alert | None, bool]:
    """Check if price is within a zone and alert ONCE only (no re-alerts)."""
    key = f"{symbol}_{alert_type}"
    entry = state.get(key, {"alerted": False})
    in_zone = low <= price <= high
    changed = False

    if in_zone and not entry.get("alerted", False):
        # First time entering zone - alert and mark as alerted
        state[key] = {
            "alerted": True,
            "alerted_at": now.isoformat(),
        }
        changed = True
        return Alert(
            symbol=symbol,
            alert_type=alert_type,
            current_price=price,
            threshold=low,
        ), changed

    # Once alerted, never alert again for this symbol+alert_type combination
    return None, changed


def check_threshold_below_once(
    state: dict,
    symbol: str,
    alert_type: str,
    price: float,
    threshold: float,
    now: datetime,
) -> tuple[Alert | None, bool]:
    """Check if price dropped below threshold and alert ONCE only (no re-alerts)."""
    key = f"{symbol}_{alert_type}"
    entry = state.get(key, {"alerted": False})
    triggered = price <= threshold
    changed = False

    logger.debug(
        "%s %s: price=%.0f threshold=%.0f triggered=%s alerted=%s",
        alert_type, symbol, price, threshold, triggered, entry.get("alerted", False),
    )

    if triggered and not entry.get("alerted", False):
        # First time hitting threshold - alert and mark as alerted
        state[key] = {
            "alerted": True,
            "alerted_at": now.isoformat(),
        }
        changed = True
        return Alert(
            symbol=symbol,
            alert_type=alert_type,
            current_price=price,
            threshold=threshold,
        ), changed

    # Once alerted, never alert again for this symbol+alert_type combination
    return None, changed


def check_threshold_above_once(
    state: dict,
    symbol: str,
    alert_type: str,
    price: float,
    threshold: float,
    now: datetime,
) -> tuple[Alert | None, bool]:
    """Check if price rose above threshold and alert ONCE only (no re-alerts)."""
    key = f"{symbol}_{alert_type}"
    entry = state.get(key, {"alerted": False})
    triggered = price >= threshold
    changed = False

    if triggered and not entry.get("alerted", False):
        # First time hitting threshold - alert and mark as alerted
        state[key] = {
            "alerted": True,
            "alerted_at": now.isoformat(),
        }
        changed = True
        return Alert(
            symbol=symbol,
            alert_type=alert_type,
            current_price=price,
            threshold=threshold,
        ), changed

    # Once alerted, never alert again for this symbol+alert_type combination
    return None, changed