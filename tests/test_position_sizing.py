"""Test position sizing is config-driven and has no hard-coded values."""

import pytest
from src.strategies.trend_momentum_atr_regime_adaptive import (
    _compute_alloc_pct,
    _apply_regime_multiplier,
)


def test_fixed_pct_mode():
    """Test fixed_pct mode uses configured value."""
    config = {
        "allocation": {
            "alloc_mode": "fixed_pct",
            "fixed_alloc_pct_per_trade": 0.08,
            "min_alloc_pct": 0.03,
            "max_alloc_pct": 0.15,
        }
    }

    result = _compute_alloc_pct(config, entry_price=100, sl=95)
    assert result == 0.08, f"Expected 0.08, got {result}"


def test_fixed_pct_mode_with_different_value():
    """Test changing fixed_pct changes position size."""
    config1 = {
        "allocation": {
            "alloc_mode": "fixed_pct",
            "fixed_alloc_pct_per_trade": 0.10,
            "min_alloc_pct": 0.03,
            "max_alloc_pct": 0.15,
        }
    }

    config2 = {
        "allocation": {
            "alloc_mode": "fixed_pct",
            "fixed_alloc_pct_per_trade": 0.12,
            "min_alloc_pct": 0.03,
            "max_alloc_pct": 0.15,
        }
    }

    result1 = _compute_alloc_pct(config1, entry_price=100, sl=95)
    result2 = _compute_alloc_pct(config2, entry_price=100, sl=95)

    assert result1 == 0.10, f"Expected 0.10, got {result1}"
    assert result2 == 0.12, f"Expected 0.12, got {result2}"
    assert result1 != result2, "Position size should change with different fixed_pct"


def test_fixed_pct_mode_clamping():
    """Test fixed_pct mode respects min/max bounds."""
    # Test max clamping
    config_high = {
        "allocation": {
            "alloc_mode": "fixed_pct",
            "fixed_alloc_pct_per_trade": 0.20,  # Above max
            "min_alloc_pct": 0.03,
            "max_alloc_pct": 0.15,
        }
    }
    result_high = _compute_alloc_pct(config_high, entry_price=100, sl=95)
    assert result_high == 0.15, f"Should be clamped to max 0.15, got {result_high}"

    # Test min clamping
    config_low = {
        "allocation": {
            "alloc_mode": "fixed_pct",
            "fixed_alloc_pct_per_trade": 0.01,  # Below min
            "min_alloc_pct": 0.03,
            "max_alloc_pct": 0.15,
        }
    }
    result_low = _compute_alloc_pct(config_low, entry_price=100, sl=95)
    assert result_low == 0.03, f"Should be clamped to min 0.03, got {result_low}"


def test_risk_based_mode():
    """Test risk_based mode calculates based on stop distance."""
    config = {
        "allocation": {
            "alloc_mode": "risk_based",
            "risk_per_trade_pct": 0.01,  # Risk 1% of equity
            "min_alloc_pct": 0.03,
            "max_alloc_pct": 0.15,
        }
    }

    # 5% stop distance: risk 1% / 5% = 20% position
    result = _compute_alloc_pct(config, entry_price=100, sl=95)
    expected = 0.01 / 0.05  # 0.20, but will be clamped to max 0.15
    assert result == 0.15, f"Expected 0.15 (clamped), got {result}"

    # 10% stop distance: risk 1% / 10% = 10% position
    result = _compute_alloc_pct(config, entry_price=100, sl=90)
    expected = 0.01 / 0.10  # 0.10
    assert result == 0.10, f"Expected 0.10, got {result}"

    # 1% stop distance: risk 1% / 1% = 100% position (will be clamped)
    result = _compute_alloc_pct(config, entry_price=100, sl=99)
    assert result == 0.15, f"Expected 0.15 (clamped to max), got {result}"


def test_regime_multiplier_bull():
    """Test bull regime multiplier increases position size."""
    config = {
        "allocation": {
            "min_alloc_pct": 0.03,
            "max_alloc_pct": 0.15,
        }
    }

    base_alloc = 0.10
    bull_multiplier = 1.5

    result = _apply_regime_multiplier(base_alloc, bull_multiplier, config)
    assert result == 0.15, f"Expected 0.15 (10% * 1.5 = 15%), got {result}"


def test_regime_multiplier_bear():
    """Test bear regime multiplier decreases position size."""
    config = {
        "allocation": {
            "min_alloc_pct": 0.03,
            "max_alloc_pct": 0.15,
        }
    }

    base_alloc = 0.10
    bear_multiplier = 0.7

    result = _apply_regime_multiplier(base_alloc, bear_multiplier, config)
    assert result == 0.07, f"Expected 0.07 (10% * 0.7 = 7%), got {result}"


def test_regime_multiplier_sideways():
    """Test sideways regime uses base allocation."""
    config = {
        "allocation": {
            "min_alloc_pct": 0.03,
            "max_alloc_pct": 0.15,
        }
    }

    base_alloc = 0.10
    sideways_multiplier = 1.0

    result = _apply_regime_multiplier(base_alloc, sideways_multiplier, config)
    assert result == 0.10, f"Expected 0.10 (10% * 1.0 = 10%), got {result}"


def test_regime_multiplier_clamping():
    """Test regime multiplier respects min/max bounds."""
    config = {
        "allocation": {
            "min_alloc_pct": 0.03,
            "max_alloc_pct": 0.15,
        }
    }

    # Test max clamping with aggressive multiplier
    base_alloc = 0.12
    aggressive_multiplier = 2.0  # 12% * 2.0 = 24%, should clamp to 15%

    result = _apply_regime_multiplier(base_alloc, aggressive_multiplier, config)
    assert result == 0.15, f"Expected 0.15 (clamped), got {result}"

    # Test min clamping with defensive multiplier
    base_alloc = 0.05
    defensive_multiplier = 0.5  # 5% * 0.5 = 2.5%, should clamp to 3%

    result = _apply_regime_multiplier(base_alloc, defensive_multiplier, config)
    assert result == 0.03, f"Expected 0.03 (clamped), got {result}"


def test_no_hardcoded_015():
    """Test there are no hard-coded 0.15 values in position sizing."""
    # This test verifies that position size comes from config, not hard-coded values
    config_08 = {
        "allocation": {
            "alloc_mode": "fixed_pct",
            "fixed_alloc_pct_per_trade": 0.08,
            "min_alloc_pct": 0.03,
            "max_alloc_pct": 0.20,
        }
    }

    config_12 = {
        "allocation": {
            "alloc_mode": "fixed_pct",
            "fixed_alloc_pct_per_trade": 0.12,
            "min_alloc_pct": 0.03,
            "max_alloc_pct": 0.20,
        }
    }

    result_08 = _compute_alloc_pct(config_08, entry_price=100, sl=95)
    result_12 = _compute_alloc_pct(config_12, entry_price=100, sl=95)

    # Neither should be 0.15 if we're using 0.08 and 0.12
    assert result_08 != 0.15, "Position size should not be hard-coded to 0.15"
    assert result_12 != 0.15, "Position size should not be hard-coded to 0.15"
    assert result_08 == 0.08, f"Expected 0.08, got {result_08}"
    assert result_12 == 0.12, f"Expected 0.12, got {result_12}"


if __name__ == "__main__":
    # Run tests
    test_fixed_pct_mode()
    test_fixed_pct_mode_with_different_value()
    test_fixed_pct_mode_clamping()
    test_risk_based_mode()
    test_regime_multiplier_bull()
    test_regime_multiplier_bear()
    test_regime_multiplier_sideways()
    test_regime_multiplier_clamping()
    test_no_hardcoded_015()
    print("✅ All position sizing tests passed!")
