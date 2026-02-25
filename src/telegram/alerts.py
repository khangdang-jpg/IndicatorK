"""Alert checker — price zone detection with dedup logic."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from src.models import Alert, WeeklyPlan

logger = logging.getLogger(__name__)

ALERTS_STATE_PATH = "data/alerts_state.json"
REALERT_HOURS = 24


def load_alerts_state(path: str = ALERTS_STATE_PATH) -> dict:
    p = Path(path)
    if p.exists():
        try:
            with open(p) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_alerts_state(state: dict, path: str = ALERTS_STATE_PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(state, f, indent=2)


def check_alerts(
    plan: WeeklyPlan,
    current_prices: dict[str, float],
    alerts_state: dict,
) -> tuple[list[Alert], dict, bool]:
    """Check all recommendations against current prices.

    Returns (alerts_to_send, updated_state, state_changed).
    """
    alerts = []
    state_changed = False
    now = datetime.utcnow()

    for rec in plan.recommendations:
        sym = rec.symbol
        price = current_prices.get(sym)
        if price is None:
            continue

        # Check buy zone
        if rec.buy_zone_low > 0 and rec.buy_zone_high > 0:
            alert, changed = _check_zone(
                alerts_state, sym, "ENTERED_BUY_ZONE",
                price, rec.buy_zone_low, rec.buy_zone_high, now,
            )
            if alert:
                alert.message = (
                    f"BUY ZONE {sym}: {price:,.0f} "
                    f"(zone {rec.buy_zone_low:,.0f}-{rec.buy_zone_high:,.0f})"
                )
                alerts.append(alert)
            if changed:
                state_changed = True

        # Check stop loss
        if rec.stop_loss > 0:
            alert, changed = _check_threshold_below(
                alerts_state, sym, "STOP_LOSS_HIT",
                price, rec.stop_loss, now,
            )
            if alert:
                alert.message = (
                    f"STOP LOSS {sym}: {price:,.0f} <= {rec.stop_loss:,.0f}"
                )
                alerts.append(alert)
            if changed:
                state_changed = True

        # Check take profit
        if rec.take_profit > 0:
            alert, changed = _check_threshold_above(
                alerts_state, sym, "TAKE_PROFIT_HIT",
                price, rec.take_profit, now,
            )
            if alert:
                alert.message = (
                    f"TAKE PROFIT {sym}: {price:,.0f} >= {rec.take_profit:,.0f}"
                )
                alerts.append(alert)
            if changed:
                state_changed = True

    return alerts, alerts_state, state_changed


def _check_zone(
    state: dict,
    symbol: str,
    alert_type: str,
    price: float,
    low: float,
    high: float,
    now: datetime,
) -> tuple[Alert | None, bool]:
    """Check if price is within a zone and handle dedup."""
    key = f"{symbol}_{alert_type}"
    entry = state.get(key, {"inside_zone": False, "last_alerted_at": None})
    was_inside = entry.get("inside_zone", False)
    in_zone = low <= price <= high
    changed = False

    if in_zone:
        should_alert = False
        if not was_inside:
            # Newly entered zone
            should_alert = True
        else:
            # Already inside — re-alert after 24h
            last = entry.get("last_alerted_at")
            if last:
                try:
                    last_dt = datetime.fromisoformat(last)
                    if now - last_dt > timedelta(hours=REALERT_HOURS):
                        should_alert = True
                except (ValueError, TypeError):
                    should_alert = True
            else:
                should_alert = True

        if should_alert:
            state[key] = {
                "inside_zone": True,
                "last_alerted_at": now.isoformat(),
            }
            changed = True
            return Alert(
                symbol=symbol,
                alert_type=alert_type,
                current_price=price,
                threshold=low,
            ), changed
        elif not was_inside:
            # Entered zone but already alerted recently (shouldn't happen, but safe)
            state[key] = {
                "inside_zone": True,
                "last_alerted_at": entry.get("last_alerted_at"),
            }
            changed = True
            return None, changed
    else:
        if was_inside:
            state[key] = {"inside_zone": False, "last_alerted_at": entry.get("last_alerted_at")}
            changed = True
        return None, changed

    return None, changed


def _check_threshold_below(
    state: dict,
    symbol: str,
    alert_type: str,
    price: float,
    threshold: float,
    now: datetime,
) -> tuple[Alert | None, bool]:
    """Check if price dropped below a threshold."""
    key = f"{symbol}_{alert_type}"
    entry = state.get(key, {"inside_zone": False, "last_alerted_at": None})
    was_inside = entry.get("inside_zone", False)
    triggered = price <= threshold
    changed = False

    if triggered:
        should_alert = False
        if not was_inside:
            should_alert = True
        else:
            last = entry.get("last_alerted_at")
            if last:
                try:
                    last_dt = datetime.fromisoformat(last)
                    if now - last_dt > timedelta(hours=REALERT_HOURS):
                        should_alert = True
                except (ValueError, TypeError):
                    should_alert = True
            else:
                should_alert = True

        state[key] = {"inside_zone": True, "last_alerted_at": now.isoformat() if should_alert else entry.get("last_alerted_at")}
        changed = was_inside != True or should_alert
        if should_alert:
            return Alert(
                symbol=symbol, alert_type=alert_type,
                current_price=price, threshold=threshold,
            ), changed
    else:
        if was_inside:
            state[key] = {"inside_zone": False, "last_alerted_at": entry.get("last_alerted_at")}
            changed = True

    return None, changed


def _check_threshold_above(
    state: dict,
    symbol: str,
    alert_type: str,
    price: float,
    threshold: float,
    now: datetime,
) -> tuple[Alert | None, bool]:
    """Check if price rose above a threshold."""
    key = f"{symbol}_{alert_type}"
    entry = state.get(key, {"inside_zone": False, "last_alerted_at": None})
    was_inside = entry.get("inside_zone", False)
    triggered = price >= threshold
    changed = False

    if triggered:
        should_alert = False
        if not was_inside:
            should_alert = True
        else:
            last = entry.get("last_alerted_at")
            if last:
                try:
                    last_dt = datetime.fromisoformat(last)
                    if now - last_dt > timedelta(hours=REALERT_HOURS):
                        should_alert = True
                except (ValueError, TypeError):
                    should_alert = True
            else:
                should_alert = True

        state[key] = {"inside_zone": True, "last_alerted_at": now.isoformat() if should_alert else entry.get("last_alerted_at")}
        changed = was_inside != True or should_alert
        if should_alert:
            return Alert(
                symbol=symbol, alert_type=alert_type,
                current_price=price, threshold=threshold,
            ), changed
    else:
        if was_inside:
            state[key] = {"inside_zone": False, "last_alerted_at": entry.get("last_alerted_at")}
            changed = True

    return None, changed
