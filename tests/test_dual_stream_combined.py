from src.models import Recommendation
from src.strategies.dual_stream_combined import DualStreamCombined


def _rec(entry_price: float, stop_loss: float) -> Recommendation:
    return Recommendation(
        symbol="HPG",
        asset_class="stock",
        action="BUY",
        buy_zone_low=entry_price,
        buy_zone_high=entry_price,
        stop_loss=stop_loss,
        take_profit=entry_price * 1.1,
        position_target_pct=0.0,
        entry_price=entry_price,
    )


def test_combined_strategy_uses_allocation_risk_config_and_caps_position():
    strategy = DualStreamCombined(params={"max_combined_position": 0.25})
    config = {
        "allocation": {
            "risk_per_trade_pct": 0.01,
            "min_alloc_pct": 0.03,
            "max_alloc_pct": 0.15,
        },
        "position": {
            "max_single_position_pct": 0.15,
            "max_single_position_pct_bear": 0.10,
        },
    }

    # 2% stop distance -> raw risk sizing is 50%, so this should cap at 15%.
    position_pct = strategy._calculate_risk_based_position_size(
        _rec(entry_price=100.0, stop_loss=98.0),
        config,
        market_regime="bull",
    )

    assert position_pct == 0.15


def test_combined_strategy_applies_bear_cap_from_position_config():
    strategy = DualStreamCombined(params={"max_combined_position": 0.25})
    config = {
        "allocation": {
            "risk_per_trade_pct": 0.01,
            "min_alloc_pct": 0.03,
            "max_alloc_pct": 0.15,
        },
        "position": {
            "max_single_position_pct": 0.15,
            "max_single_position_pct_bear": 0.10,
        },
    }

    position_pct = strategy._calculate_risk_based_position_size(
        _rec(entry_price=100.0, stop_loss=98.0),
        config,
        market_regime="bear",
    )

    assert position_pct == 0.10
