# Gemini Analyzer Patch Summary

## Issues Fixed

### 1. ✅ Model Update
- **Issue**: `gemini-2.0-flash` deprecated
- **Solution**: Already using `gemini-2.5-flash-lite` as default
- **Enhancement**: Added `_get_model()` function with `GEMINI_MODEL` env var override
- **Usage**: `export GEMINI_MODEL="gemini-2.5-flash"` to use full model

### 2. ✅ Prompt Data Integrity
- **Issue**: Prompt asked for macro/sector context without providing data → hallucination risk
- **Solution**:
  - Added `CRITICAL: Use ONLY the provided data` warning
  - Added `market_snapshot` parameter for optional market context
  - If no market snapshot provided, AI must respond with "Insufficient market context"
  - Added `as_of_timestamp` for data freshness awareness

### 3. ✅ Weekly Trading Rubric
- **Issue**: Generic scoring criteria
- **Solution**: Completely rewritten scoring criteria for weekly trading:
  - **Weekly trend alignment**: MA10w > MA30w confirmation
  - **Technical setup**: RSI(14) and ATR(14) context
  - **Entry types**: BREAKOUT (T+1 confirmation) vs PULLBACK (ATR mid-zone)
  - **Vietnamese market**: Tick-step rounding, liquidity considerations
  - **Risk/reward**: ATR-based SL distances, minimum 1.5:1 ratios

### 4. ✅ JSON Strictness
- **Issue**: Need stricter JSON enforcement
- **Solution**: Enhanced prompt with:
  - "Respond with ONLY valid JSON, no markdown formatting, no additional text"
  - "If you cannot comply with this format, return {}"
  - Still using `responseMimeType: "application/json"`

### 5. ✅ Data Freshness
- **Issue**: No timestamp context
- **Solution**:
  - Added `as_of_timestamp` parameter to `analyze_weekly_plan()`
  - Auto-generates current UTC timestamp if not provided
  - Includes in prompt: "DATA AS OF: {timestamp}"
  - AI must reference provided data timing, not "latest market" assumptions

## Function Signature Changes

### `analyze_weekly_plan()` - Updated
```python
def analyze_weekly_plan(
    plan_dict: dict,
    portfolio_summary: str = "",
    as_of_timestamp: str = "",      # NEW: ISO timestamp
    market_snapshot: str = "",      # NEW: optional market data
) -> AIAnalysis:
```

### `_build_scoring_prompt()` - Updated
```python
def _build_scoring_prompt(
    recommendations: list[dict],
    portfolio_summary: str,
    as_of_timestamp: str = "",      # NEW
    market_snapshot: str = ""       # NEW
) -> str:
```

## New Scoring Criteria (Weekly Focus)

1. **Weekly Trend Alignment** (MA10w vs MA30w)
2. **RSI(14) Context** (<30 = pullback, >70 = breakout strength)
3. **ATR(14) Setup Quality** (SL distance, entry timing)
4. **Entry Type Validation** (breakout confirmation, pullback zones)
5. **Vietnamese Market Factors** (tick-step rounding, liquidity)
6. **Risk/Reward Optimization** (1.5:1 minimum, ATR-based stops)

## Usage Examples

### Basic Usage (Backward Compatible)
```python
analysis = analyze_weekly_plan(plan_dict, portfolio_summary)
```

### Full Featured Usage
```python
analysis = analyze_weekly_plan(
    plan_dict=plan,
    portfolio_summary="60% cash, 40% stocks...",
    as_of_timestamp="2026-03-01T10:30:00Z",
    market_snapshot="VN-Index: 1,247 (+0.8% weekly)..."
)
```

### Model Override
```bash
export GEMINI_MODEL="gemini-2.5-flash"  # Use full model instead of lite
```

## Expected Output Format

```json
{
  "scores": {
    "VHM": {
      "score": 8,
      "rationale": "Weekly MA10w > MA30w with RSI(14) at 68 showing breakout strength",
      "risk_note": ""
    },
    "VIC": {
      "score": 7,
      "rationale": "Good pullback setup with RSI(14) at 42 and ATR mid-zone touch",
      "risk_note": ""
    }
  },
  "market_context": "VN-Index showing weekly strength with foreign net buying support."
}
```

## Files Modified

- `src/ai/gemini_analyzer.py` - Core implementation
- `example_gemini_usage.py` - Usage demonstration (NEW)

## Testing

Run the example script to verify functionality:
```bash
export GEMINI_API_KEY="your_key_here"
python example_gemini_usage.py
```

The script tests both scenarios:
1. With market snapshot (should provide full market context)
2. Without market snapshot (should state "Insufficient market context")

## Backward Compatibility

✅ **Fully backward compatible** - existing code will work unchanged
- New parameters are optional with sensible defaults
- Existing function signatures still work
- Graceful fallbacks for missing data