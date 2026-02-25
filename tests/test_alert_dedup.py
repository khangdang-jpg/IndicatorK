"""Tests for alert deduplication logic."""

from datetime import datetime, timedelta

import pytest

from src.models import Recommendation, WeeklyPlan
from src.telegram.alerts import check_alerts


def _make_plan(recs: list[Recommendation]) -> WeeklyPlan:
    return WeeklyPlan(
        generated_at="2025-01-01T00:00:00",
        strategy_id="test",
        strategy_version="1.0",
        allocation_targets={"stock": 0.5, "bond_fund": 0.5},
        recommendations=recs,
    )


def _make_rec(
    symbol="HPG",
    buy_zone_low=24000,
    buy_zone_high=25000,
    stop_loss=22000,
    take_profit=30000,
) -> Recommendation:
    return Recommendation(
        symbol=symbol,
        asset_class="stock",
        action="BUY",
        buy_zone_low=buy_zone_low,
        buy_zone_high=buy_zone_high,
        stop_loss=stop_loss,
        take_profit=take_profit,
        position_target_pct=0.15,
    )


class TestBuyZoneAlert:
    def test_enter_buy_zone(self):
        plan = _make_plan([_make_rec()])
        prices = {"HPG": 24500}  # Inside zone
        alerts, state, changed = check_alerts(plan, prices, {})
        buy_alerts = [a for a in alerts if a.alert_type == "ENTERED_BUY_ZONE"]
        assert len(buy_alerts) == 1
        assert buy_alerts[0].symbol == "HPG"
        assert changed is True

    def test_outside_buy_zone_no_alert(self):
        plan = _make_plan([_make_rec()])
        prices = {"HPG": 26000}  # Above zone
        alerts, state, changed = check_alerts(plan, prices, {})
        buy_alerts = [a for a in alerts if a.alert_type == "ENTERED_BUY_ZONE"]
        assert len(buy_alerts) == 0

    def test_dedup_same_zone(self):
        """Already inside zone, recently alerted -> no re-alert."""
        plan = _make_plan([_make_rec()])
        now = datetime.utcnow()
        state = {
            "HPG_ENTERED_BUY_ZONE": {
                "inside_zone": True,
                "last_alerted_at": now.isoformat(),
            }
        }
        prices = {"HPG": 24500}
        alerts, _, _ = check_alerts(plan, prices, state)
        buy_alerts = [a for a in alerts if a.alert_type == "ENTERED_BUY_ZONE"]
        assert len(buy_alerts) == 0

    def test_realert_after_24h(self):
        """Inside zone but last alert > 24h ago -> re-alert."""
        plan = _make_plan([_make_rec()])
        old_time = (datetime.utcnow() - timedelta(hours=25)).isoformat()
        state = {
            "HPG_ENTERED_BUY_ZONE": {
                "inside_zone": True,
                "last_alerted_at": old_time,
            }
        }
        prices = {"HPG": 24500}
        alerts, _, changed = check_alerts(plan, prices, state)
        buy_alerts = [a for a in alerts if a.alert_type == "ENTERED_BUY_ZONE"]
        assert len(buy_alerts) == 1
        assert changed is True

    def test_exit_then_reenter(self):
        """Exit zone -> re-enter -> should alert."""
        plan = _make_plan([_make_rec()])
        now = datetime.utcnow()

        # Step 1: Already inside zone
        state = {
            "HPG_ENTERED_BUY_ZONE": {
                "inside_zone": True,
                "last_alerted_at": now.isoformat(),
            }
        }

        # Step 2: Exit zone
        prices_exit = {"HPG": 26000}
        alerts, state, _ = check_alerts(plan, prices_exit, state)
        assert state["HPG_ENTERED_BUY_ZONE"]["inside_zone"] is False

        # Step 3: Re-enter zone -> should alert
        prices_enter = {"HPG": 24500}
        alerts, state, changed = check_alerts(plan, prices_enter, state)
        buy_alerts = [a for a in alerts if a.alert_type == "ENTERED_BUY_ZONE"]
        assert len(buy_alerts) == 1
        assert changed is True


class TestStopLossAlert:
    def test_stop_loss_hit(self):
        plan = _make_plan([_make_rec(stop_loss=22000)])
        prices = {"HPG": 21000}  # Below stop
        alerts, state, changed = check_alerts(plan, prices, {})
        sl_alerts = [a for a in alerts if a.alert_type == "STOP_LOSS_HIT"]
        assert len(sl_alerts) == 1
        assert changed is True

    def test_stop_loss_not_hit(self):
        plan = _make_plan([_make_rec(stop_loss=22000)])
        prices = {"HPG": 23000}  # Above stop
        alerts, _, _ = check_alerts(plan, prices, {})
        sl_alerts = [a for a in alerts if a.alert_type == "STOP_LOSS_HIT"]
        assert len(sl_alerts) == 0


class TestTakeProfitAlert:
    def test_take_profit_hit(self):
        plan = _make_plan([_make_rec(take_profit=30000)])
        prices = {"HPG": 31000}  # Above target
        alerts, state, changed = check_alerts(plan, prices, {})
        tp_alerts = [a for a in alerts if a.alert_type == "TAKE_PROFIT_HIT"]
        assert len(tp_alerts) == 1
        assert changed is True

    def test_take_profit_not_hit(self):
        plan = _make_plan([_make_rec(take_profit=30000)])
        prices = {"HPG": 29000}
        alerts, _, _ = check_alerts(plan, prices, {})
        tp_alerts = [a for a in alerts if a.alert_type == "TAKE_PROFIT_HIT"]
        assert len(tp_alerts) == 0


class TestMissingPrice:
    def test_no_price_no_alert(self):
        plan = _make_plan([_make_rec()])
        prices = {}  # No price for HPG
        alerts, _, _ = check_alerts(plan, prices, {})
        assert len(alerts) == 0


class TestStateChanged:
    def test_no_change_when_outside_zone(self):
        plan = _make_plan([_make_rec()])
        prices = {"HPG": 26000}  # Outside all zones
        alerts, state, changed = check_alerts(plan, prices, {})
        assert changed is False

    def test_change_on_zone_entry(self):
        plan = _make_plan([_make_rec()])
        prices = {"HPG": 24500}
        alerts, state, changed = check_alerts(plan, prices, {})
        assert changed is True
