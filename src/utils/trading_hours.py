"""Vietnam trading hours gate (Asia/Ho_Chi_Minh)."""

from __future__ import annotations

from datetime import datetime, time

import pytz

VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")

MORNING_OPEN = time(9, 0)
MORNING_CLOSE = time(11, 30)
AFTERNOON_OPEN = time(13, 0)
AFTERNOON_CLOSE = time(15, 0)


def get_vietnam_now() -> datetime:
    return datetime.now(VN_TZ)


def is_trading_hours(now: datetime | None = None) -> bool:
    """Check if the given time falls within Vietnam stock trading hours.

    Trading hours: Mon-Fri, 09:00-11:30 and 13:00-15:00 (Asia/Ho_Chi_Minh).
    No holiday calendar — only weekday check.
    """
    if now is None:
        now = get_vietnam_now()

    if now.tzinfo is None:
        now = VN_TZ.localize(now)
    else:
        now = now.astimezone(VN_TZ)

    # Mon=0 .. Fri=4
    if now.weekday() > 4:
        return False

    t = now.time()
    in_morning = MORNING_OPEN <= t <= MORNING_CLOSE
    in_afternoon = AFTERNOON_OPEN <= t <= AFTERNOON_CLOSE
    return in_morning or in_afternoon
