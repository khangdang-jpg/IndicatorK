# Position Sizing Fix - Config-Driven Allocation

## Problem
The regime-adaptive strategy had hard-coded position sizes (e.g., 15% for bull, 7% for bear) instead of using the config-driven allocation system from `config/risk.yml`.

## Solution
Implemented proper config-driven position sizing with regime-specific multipliers:

### 1. Base Allocation (from config/risk.yml)
- **fixed_pct mode**: Use `fixed_alloc_pct_per_trade` directly
- **risk_based mode**: Calculate based on stop distance: `risk_per_trade_pct / stop_distance_pct`
- Both modes respect `min_alloc_pct` and `max_alloc_pct` bounds

### 2. Regime Multipliers (from config/strategy.yml)
- **BULL**: 1.5x base allocation (aggressive)
- **BEAR**: 0.7x base allocation (defensive)
- **SIDEWAYS**: 1.0x base allocation (balanced)

### 3. Final Position Size
```
final_position = clamp(base_allocation * regime_multiplier, min_alloc_pct, max_alloc_pct)
```

## Changes Made

### src/strategies/trend_momentum_atr_regime_adaptive.py
- Replaced hard-coded `bull_position_pct`, `bear_position_pct`, `sideways_position_pct` with `*_position_multiplier`
- Added `_compute_alloc_pct()` function for base allocation calculation
- Added `_apply_regime_multiplier()` function for regime-adjusted sizing
- Updated position sizing logic to use config + regime multiplier

### config/strategy.yml
- Changed from `bull_position_pct: 0.15` to `bull_position_multiplier: 1.5`
- Changed from `bear_position_pct: 0.07` to `bear_position_multiplier: 0.7`
- Changed from `sideways_position_pct: 0.10` to `sideways_position_multiplier: 1.0`

### tests/test_position_sizing.py
- Created comprehensive test suite for position sizing logic
- Tests fixed_pct mode, risk_based mode, regime multipliers, and clamping
- Verifies no hard-coded 0.15 values

## Verification

### Test Results
```bash
✅ All position sizing tests passed!

Testing with current config (fixed_pct=0.12):
  Base allocation: 12.00%
  BULL position (1.5x): 15.00%
  BEAR position (0.7x): 8.40%
  SIDEWAYS position (1.0x): 12.00%
```

### Backtest Results

#### Downtrend (2022-01-01 to 2023-01-01)
- Regime detected: BEAR (0.70x base multiplier)
- CAGR: -9.88%
- Max Drawdown: 17.68%
- Trades: 20

#### Uptrend (2025-03-01 to 2026-03-01)
- Regime detected: BULL (1.50x base multiplier)
- CAGR: 36.62%
- Max Drawdown: 9.76%
- Trades: 22

## Benefits

1. **Config-Driven**: All position sizing controlled via `config/risk.yml`
2. **Flexible**: Supports both fixed_pct and risk_based allocation modes
3. **Regime-Aware**: Automatically adjusts sizing based on market conditions
4. **Bounded**: Always respects min/max allocation limits
5. **Testable**: Clear separation of concerns with testable functions

## Usage

### To change base position size:
Edit `config/risk.yml`:
```yaml
allocation:
  alloc_mode: "fixed_pct"
  fixed_alloc_pct_per_trade: 0.10  # Change this value
  min_alloc_pct: 0.03
  max_alloc_pct: 0.15
```

### To change regime multipliers:
Edit `config/strategy.yml`:
```yaml
trend_momentum_atr_regime_adaptive:
  bull_position_multiplier: 1.5    # Adjust multipliers
  bear_position_multiplier: 0.7
  sideways_position_multiplier: 1.0
```

### To use risk-based sizing:
Edit `config/risk.yml`:
```yaml
allocation:
  alloc_mode: "risk_based"
  risk_per_trade_pct: 0.01  # Risk 1% of equity per trade
```

## No More Hard-Coded Values

Position sizing is now fully config-driven with no hard-coded percentages in the strategy code.
