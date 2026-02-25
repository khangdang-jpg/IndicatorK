"""Tests for Vietnam trading hours gate."""

from datetime import datetime

import pytz
import pytest

from src.utils.trading_hours import VN_TZ, is_trading_hours


class TestTradingHours:
    def _make_dt(self, year, month, day, hour, minute):
        return VN_TZ.localize(datetime(year, month, day, hour, minute))

    def test_morning_session_open(self):
        # Mon 09:00 ICT -> inside
        dt = self._make_dt(2025, 1, 6, 9, 0)
        assert is_trading_hours(dt) is True

    def test_morning_session_mid(self):
        # Mon 10:30 ICT -> inside
        dt = self._make_dt(2025, 1, 6, 10, 30)
        assert is_trading_hours(dt) is True

    def test_morning_session_close(self):
        # Mon 11:30 ICT -> inside (boundary)
        dt = self._make_dt(2025, 1, 6, 11, 30)
        assert is_trading_hours(dt) is True

    def test_lunch_break(self):
        # Mon 12:00 ICT -> outside
        dt = self._make_dt(2025, 1, 6, 12, 0)
        assert is_trading_hours(dt) is False

    def test_afternoon_session_open(self):
        # Mon 13:00 ICT -> inside
        dt = self._make_dt(2025, 1, 6, 13, 0)
        assert is_trading_hours(dt) is True

    def test_afternoon_session_close(self):
        # Mon 15:00 ICT -> inside (boundary)
        dt = self._make_dt(2025, 1, 6, 15, 0)
        assert is_trading_hours(dt) is True

    def test_after_close(self):
        # Mon 15:01 ICT -> outside
        dt = self._make_dt(2025, 1, 6, 15, 1)
        assert is_trading_hours(dt) is False

    def test_before_open(self):
        # Mon 08:59 ICT -> outside
        dt = self._make_dt(2025, 1, 6, 8, 59)
        assert is_trading_hours(dt) is False

    def test_saturday(self):
        # Sat 10:00 ICT -> outside (weekend)
        dt = self._make_dt(2025, 1, 4, 10, 0)
        assert is_trading_hours(dt) is False

    def test_sunday(self):
        # Sun 10:00 ICT -> outside (weekend)
        dt = self._make_dt(2025, 1, 5, 10, 0)
        assert is_trading_hours(dt) is False

    def test_friday_morning(self):
        # Fri 10:00 ICT -> inside
        dt = self._make_dt(2025, 1, 10, 10, 0)
        assert is_trading_hours(dt) is True

    def test_between_sessions(self):
        # Mon 11:31 ICT -> outside (between sessions)
        dt = self._make_dt(2025, 1, 6, 11, 31)
        assert is_trading_hours(dt) is False

    def test_utc_conversion(self):
        # 03:00 UTC = 10:00 ICT on Monday -> inside
        utc = pytz.utc.localize(datetime(2025, 1, 6, 3, 0))
        assert is_trading_hours(utc) is True

    def test_late_night_utc(self):
        # 22:00 UTC = 05:00 ICT next day -> outside
        utc = pytz.utc.localize(datetime(2025, 1, 5, 22, 0))
        assert is_trading_hours(utc) is False

    def test_naive_datetime_treated_as_local(self):
        # Naive datetime is localized to ICT
        dt = datetime(2025, 1, 6, 10, 0)
        assert is_trading_hours(dt) is True
