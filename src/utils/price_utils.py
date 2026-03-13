"""Price rounding utilities for Vietnamese stock market.

Centralizes price step rounding logic to ensure consistent behavior across all strategies.
"""

import math


def round_to_step(price: float, step: float = 10.0) -> float:
    """Round price to the nearest step size (round-half-up).

    Args:
        price: The price to round
        step: The step size (default 10 VND for Vietnamese stocks)

    Returns:
        Price rounded to the nearest step using round-half-up logic

    Examples:
        round_to_step(10_014, 10) → 10_010
        round_to_step(10_015, 10) → 10_020 (round half up)
        round_to_step(10_055, 10) → 10_060
    """
    if step <= 0:
        return price
    if step < price * 0.0001:
        return round(price, 2)
    return float(math.floor(price / step + 0.5) * step)


def floor_to_step(price: float, step: float = 10.0) -> float:
    """Floor price DOWN to the nearest step — always used for stop losses.

    Ensures the SL is at or below the intended level, never rounding up.
    This is critical for risk management as we never want stop losses
    rounded in a direction that increases risk.

    Args:
        price: The price to floor
        step: The step size (default 10 VND for Vietnamese stocks)

    Returns:
        Price floored down to the nearest step

    Examples:
        floor_to_step(55, 10) → 50  (round_to_step would give 60)
        floor_to_step(23.7, 0.1) → 23.7
    """
    if step <= 0:
        return price
    return float(math.floor(price / step) * step)


def ceil_to_step(price: float, step: float = 10.0) -> float:
    """Ceil price UP to the nearest step — always used for take profits.

    Ensures the TP is at or above the intended level, never rounding down.
    This maximizes potential profit by never accidentally reducing the
    take profit target due to rounding.

    Args:
        price: The price to ceil
        step: The step size (default 10 VND for Vietnamese stocks)

    Returns:
        Price ceiled up to the nearest step

    Examples:
        ceil_to_step(75, 10) → 80
        ceil_to_step(23.2, 0.1) → 23.3
    """
    if step <= 0:
        return price
    return float(math.ceil(price / step) * step)