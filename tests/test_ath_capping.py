"""Test ATH-aware take profit capping functionality."""

from datetime import date

from src.models import OHLCV
from src.strategies.trend_momentum_atr_regime_adaptive import TrendMomentumATRRegimeAdaptive, round_to_step


class TestATHCapping:
    def test_ath_tracking_functionality(self):
        """Test that ATH tracking works correctly."""
        strategy = TrendMomentumATRRegimeAdaptive(params={
            "ath_cap_pct": 0.20,
            "ath_lookback_days": 100
        })

        # Create simple test data with clear ATH
        candles = []
        for i in range(150):
            d = date(2024, 1, 1)
            d = date.fromordinal(d.toordinal() + i)

            if i <= 50:
                price = 80000 + i * 400  # Rise to 100,000
            elif i <= 100:
                price = 100000 - (i - 50) * 300  # Fall to 85,000
            else:
                price = 85000 + (i - 100) * 100  # Rise to 90,000

            candles.append(OHLCV(
                date=d,
                open=price,
                high=price + 200,
                low=price - 200,
                close=price,
                volume=100000,
            ))

        # Test ATH tracking
        ath = strategy._update_ath_tracking("TEST", candles)

        assert "TEST" in strategy.ath_tracking
        assert strategy.ath_tracking["TEST"]["ath"] == 100200  # Should be the high from day 50
        assert ath == 100200

    def test_ath_capping_logic(self):
        """Test ATH capping logic directly without full strategy."""
        strategy = TrendMomentumATRRegimeAdaptive(params={
            "ath_cap_pct": 0.20,
            "ath_lookback_days": 100
        })

        # Mock ATH tracking
        strategy.ath_tracking["TEST"] = {"ath": 100000, "date": date(2024, 1, 1)}

        # Test capping logic
        entry_price = 90000
        atr = 3000
        atr_target_mult = 4.0
        tick = 10

        # Calculate raw TP (would be unrealistic)
        raw_take_profit = round_to_step(entry_price + atr_target_mult * atr, tick)

        # Get ATH capping
        current_ath = strategy.ath_tracking["TEST"]["ath"]
        ath_capped_tp = round_to_step(current_ath * (1 + strategy.ath_cap_pct), tick)

        # Apply capping
        take_profit = min(raw_take_profit, ath_capped_tp)

        # Verify capping worked
        assert raw_take_profit == 102000  # 90000 + 4 * 3000
        assert ath_capped_tp == 120000   # 100000 * 1.20
        assert take_profit == 102000     # Should use raw TP since it's lower

        # Test case where capping is needed
        atr_target_mult = 6.0  # This would create unrealistic TP
        raw_take_profit = round_to_step(entry_price + atr_target_mult * atr, tick)
        take_profit = min(raw_take_profit, ath_capped_tp)

        assert raw_take_profit == 108000  # 90000 + 6 * 3000
        assert take_profit == 108000     # Should still use raw since it's lower

        # Test case where capping is definitely needed
        atr_target_mult = 12.0
        raw_take_profit = round_to_step(entry_price + atr_target_mult * atr, tick)
        take_profit = min(raw_take_profit, ath_capped_tp)

        assert raw_take_profit == 126000  # 90000 + 12 * 3000
        assert take_profit == 120000     # Should be capped at ATH + 20%

    def test_lookback_window(self):
        """Test that ATH lookback window works correctly."""
        strategy = TrendMomentumATRRegimeAdaptive(params={
            "ath_cap_pct": 0.20,
            "ath_lookback_days": 50  # Only look back 50 days
        })

        # Create test data where older ATH should be ignored
        candles = []
        for i in range(100):
            d = date(2024, 1, 1)
            d = date.fromordinal(d.toordinal() + i)

            if i == 10:
                price = 120000  # Old ATH that should be ignored
            elif i >= 60:
                price = 90000 + (i - 60) * 200  # Recent high around 98,000
            else:
                price = 80000 + i * 100

            candles.append(OHLCV(
                date=d,
                open=price,
                high=price + 100,
                low=price - 100,
                close=price,
                volume=100000,
            ))

        # Test ATH tracking only considers last 50 days
        ath = strategy._update_ath_tracking("TEST", candles)

        # Should find ATH from recent data, not the old 120,000 peak
        assert ath < 120000  # Should not include the old ATH
        assert ath >= 97000   # Should be around the recent high (allowing for calculation precision)
