"""Vietnam trading hours gate (Asia/Ho_Chi_Minh) with holiday calendar."""

from __future__ import annotations

from datetime import date, datetime, time

import pytz

VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")

MORNING_OPEN = time(9, 0)
MORNING_CLOSE = time(11, 30)
AFTERNOON_OPEN = time(13, 0)
AFTERNOON_CLOSE = time(15, 0)

# Vietnamese public holidays (fixed dates).
# Lunar New Year (Tet) dates shift each year and must be updated annually.
# Format: (month, day) for fixed holidays, explicit dates for Tet.
_FIXED_HOLIDAYS: list[tuple[int, int]] = [
    (1, 1),    # New Year's Day
    (4, 30),   # Reunification Day
    (5, 1),    # International Workers' Day
    (9, 2),    # National Day
]

# Tet (Lunar New Year) closures — update each year.
# Includes the standard 5-day Tet closure window.
_TET_CLOSURES: dict[int, list[date]] = {
    2025: [date(2025, 1, 27), date(2025, 1, 28), date(2025, 1, 29),
           date(2025, 1, 30), date(2025, 1, 31)],
    2026: [date(2026, 2, 16), date(2026, 2, 17), date(2026, 2, 18),
           date(2026, 2, 19), date(2026, 2, 20)],
    2027: [date(2027, 2, 5), date(2027, 2, 6), date(2027, 2, 7),
           date(2027, 2, 8), date(2027, 2, 9)],
}

# Hung Kings' Commemoration Day (10th day of 3rd lunar month) — update each year.
_HUNG_KINGS: dict[int, date] = {
    2025: date(2025, 4, 7),
    2026: date(2026, 3, 27),
    2027: date(2027, 4, 15),
}


def get_vietnam_now() -> datetime:
    return datetime.now(VN_TZ)


def is_vn_holiday(d: date) -> bool:
    """Check if a date is a Vietnamese public holiday."""
    for month, day in _FIXED_HOLIDAYS:
        if d.month == month and d.day == day:
            return True
    tet_dates = _TET_CLOSURES.get(d.year, [])
    if d in tet_dates:
        return True
    hung_kings = _HUNG_KINGS.get(d.year)
    if hung_kings and d == hung_kings:
        return True
    return False


def is_trading_hours(now: datetime | None = None) -> bool:
    """Check if the given time falls within Vietnam stock trading hours.

    Trading hours: Mon-Fri, 09:00-11:30 and 13:00-15:00 (Asia/Ho_Chi_Minh).
    Excludes weekends and Vietnamese public holidays.
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

    if is_vn_holiday(now.date()):
        return False

    t = now.time()
    in_morning = MORNING_OPEN <= t <= MORNING_CLOSE
    in_afternoon = AFTERNOON_OPEN <= t <= AFTERNOON_CLOSE
    return in_morning or in_afternoon


def vnd_tick_size(price: float) -> float:
    """Return the proper VND tick size based on HOSE price bands.

    HOSE tick sizes:
      price < 10,000   -> tick = 10 VND
      10,000 <= price < 50,000 -> tick = 50 VND
      price >= 50,000   -> tick = 100 VND
    """
    if price < 10_000:
        return 10.0
    if price < 50_000:
        return 50.0
    return 100.0
