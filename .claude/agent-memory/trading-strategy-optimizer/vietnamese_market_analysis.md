# Vietnamese Market Swing Trading Research (2026-03-13)

## Key Findings for Vietnamese Stock Market Technical Analysis

### Current System Performance (Exceptional)
- **Strategy**: trend_momentum_atr_regime_adaptive
- **Performance**: 28-47% CAGR, Sharpe 3.23, Max DD 8.72-21.85%
- **Timeframe**: Weekly signals (excellent for trend following)
- **Risk Management**: ATR-based stops (proven highly effective)

### Vietnamese Market Infrastructure
- **Data Provider**: vnstock library (VCI/TCBS/DNSE sources)
- **Price Precision**: VND tick sizes - auto-adjusted via vnd_tick_size()
  - <10k VND: 0.01 steps, 10k-50k: 0.05 steps, >50k: 0.1 steps
- **Rate Limits**: 5 symbols/chunk, 1s delay between chunks
- **Error Handling**: 3-retry mechanism with exponential backoff

### Optimal Swing Trading Indicators (3-14 day holds)

#### Primary Momentum (Proven Effective)
1. **RSI(14)** - Regime adaptive thresholds:
   - Bull: ≥50, Sideways: ≥55, Bear: ≥65
   - Exit: >70 (overbought)

2. **MACD(12,26,9)** - Recommended addition:
   - Entry: MACD line > signal line + positive histogram
   - Exit: Histogram turns negative

#### Trend Following (Core System)
3. **Moving Averages** - Daily adaptation of weekly system:
   - Current: MA10w > MA30w (weekly)
   - Swing: MA10d > MA30d (daily) + weekly confirmation
   - Multi-timeframe: Daily entry with weekly trend filter

4. **Bollinger Bands(20,2)** - Enhancement opportunity:
   - Entry: Price breaks upper band + RSI confirmation
   - Exit: Price touches middle band

#### Volatility & Risk (Exceptional Performance)
5. **ATR(14)** - Cornerstone of current success:
   - Stop Loss: 1.2x-1.8x ATR (regime adaptive)
   - Take Profit: 2.0x-4.0x ATR (regime adaptive)
   - Bull: 1.8x stops, 4.0x targets (let winners run)
   - Bear: 1.2x stops, 2.0x targets (tight control)

### Regime Detection (Currently Implemented)
- **Lookback**: 60 days, Threshold: ±5%
- **Bull**: >5% gains → 1.5x position sizing, wider stops
- **Bear**: <-5% losses → 0.7x position sizing, tight stops
- **Sideways**: -5% to +5% → 1.0x balanced approach

### Multi-Timeframe Framework
1. **Weekly Trend**: Primary filter (current system)
2. **Daily Signals**: Entry timing (adaptation needed)
3. **Volume**: Current ≥ average confirmation (proven)
4. **Breakout**: Weekly high breaks (T+1 entry, no lookahead)

### Risk Management Excellence
- **Position Sizing**: Risk-based = risk_pct / stop_distance_pct
- **Risk Per Trade**: 1% of equity (proven optimal)
- **Position Limits**: 3% min, 15% max per position
- **Portfolio Max**: 60% stocks, 40% bonds/cash

### Vietnamese Market Specific Considerations
- **Psychological Levels**: 10k, 20k, 50k, 100k VND round numbers
- **ATH Capping**: Take profits capped at ATH + 20% (realistic)
- **Seasonality**: Lunar New Year, quarterly earnings (research gap)
- **Currency**: VND/USD correlation analysis needed

### Implementation Priority
1. **High**: Daily timeframe adaptation of current weekly system
2. **Medium**: MACD + Bollinger Bands addition
3. **Low**: Seasonality models, sector rotation

### Expected Performance (Daily Adaptation)
- **CAGR**: 20-35% (vs current 28-47%)
- **Sharpe**: 2.0-2.5 (vs current 3.23)
- **Max DD**: 12-18% (vs current 8.72-21.85%)
- **Trade Frequency**: 2-3x higher (daily vs weekly)

### Key Success Factors
- Maintain ATR-based risk system (core competitive advantage)
- Regime-adaptive parameters (bull/bear/sideways)
- VND price precision handling (tick size rounding)
- Volume confirmation (current ≥ average filter)
- Multi-timeframe analysis (daily + weekly)

### File References
- Strategy: src/strategies/trend_momentum_atr_regime_adaptive.py
- Config: config/strategy.yml (regime parameters)
- Risk: config/risk.yml (position sizing)
- VN Provider: src/providers/vnstock_provider.py