# Backtest Implementation Summary

## Status: ✅ COMPLETE

A fully functional backtest CLI has been implemented for evaluating weekly trading strategies on historical OHLCV data from **2025-05-01 to 2026-02-25**.

---

## What Was Built

### Core Module: `src/backtest/`

| File | Lines | Purpose |
|------|-------|---------|
| `__init__.py` | 1 | Package marker |
| `engine.py` | 265 | Touch logic + BacktestEngine (portfolio accounting, equity curve) |
| `weekly_generator.py` | 80 | Week iteration, plan loading/generation helpers |
| `reporter.py` | 130 | JSON + CSV output writers with range comparison |
| `cli.py` | 380 | CLI parsing, main orchestration, provider fallback |
| `__main__.py` | 4 | `python -m src.backtest` entry point |

### Scripts

| File | Purpose |
|------|---------|
| `scripts/backtest.py` | `python scripts/backtest.py [args]` convenience wrapper |

### Tests

| File | Count | Coverage |
|------|-------|----------|
| `tests/test_backtest.py` | 33 tests | Entry/SL/TP touch, tie-breaker, accounting, weeks |

### Documentation

| File | Purpose |
|------|---------|
| `docs/10_BACKTEST_GUIDE.md` | Full user guide with examples |
| `Makefile` | `make backtest` target with defaults |

---

## Key Features

### Entry/Exit Rules (SPEC)
- **Entry:** `mid_zone = (buy_zone_low + buy_zone_high) / 2`
- **Entry touch:** `day_low <= entry <= day_high`
- **Exit touch:** `day_low <= SL` or `day_high >= TP`
- **Same-day tie-breaker:** `worst` (SL first) or `best` (TP first)
- **No same-day entry+exit:** Realistic holding minimum

### Portfolio Accounting
- **Fixed order-size:** `qty = floor(1_000_000 / entry_price)`
- **Capital:** 10,000,000 VND initial (configurable)
- **Daily equity curve:** cash + open_positions_value
- **PnL tracking:** per-trade return_pct and pnl_vnd

### Simulation Modes
- **generate** (default): Per-week strategy regeneration with no-lookahead
- **plan:** Reuse static weekly_plan.json (offline testing)

### Output Artifacts
- **Single run:** `summary.json`, `equity_curve.csv`, `trades.csv`
- **Range run:** `summary_worst.json`, `summary_best.json`, `range_summary.json` + CSV variants
- **Metrics:** CAGR, max_drawdown, win_rate, avg_hold_days, profit_factor

### Data & Providers
- **Reuses existing provider chain:** vnstock → http → cache
- **Auto-fallback:** If vnstock unavailable, uses http → cache
- **No data required locally:** Fetches 52 weeks history before backtest range

---

## Usage Examples

### Command Line (Spec Dates: 2025-05-01 to 2026-02-25)

```bash
# Single worst-case run
python scripts/backtest.py --from 2025-05-01 --to 2026-02-25

# Range: both worst and best
python scripts/backtest.py --from 2025-05-01 --to 2026-02-25 --run-range

# Via module
python -m src.backtest --from 2025-05-01 --to 2026-02-25 --run-range
```

### Makefile

```bash
# Spec-matched defaults (10M capital, 1M per trade, 4/week)
make backtest FROM=2025-05-01 TO=2026-02-25 RUN_RANGE=1

# Custom order size
make backtest FROM=2025-05-01 TO=2026-02-25 ORDER_SIZE=500000

# Custom trades per week
make backtest FROM=2025-05-01 TO=2026-02-25 TRADES_PER_WEEK=2

# Offline (use existing weekly_plan.json for all weeks)
make backtest FROM=2025-05-01 TO=2026-02-25 MODE=plan RUN_RANGE=1
```

### Full CLI Options

```
--from YYYY-MM-DD              Backtest start [required]
--to YYYY-MM-DD                Backtest end [required]
--initial-cash INTEGER         Starting VND (default: 10000000)
--order-size INTEGER           VND per trade (default: 1000000)
--trades-per-week INTEGER      Max new positions/week (default: 4)
--universe PATH                Watchlist file (default: data/watchlist.txt)
--mode CHOICE                  'generate' or 'plan' (default: generate)
--plan-file PATH               Plan JSON for --mode plan
--tie-breaker CHOICE           'worst' or 'best' (default: worst)
--run-range                    Run both tie-breakers & compare
```

---

## Architecture Decisions

### No Same-Day Entry+Exit
Entries on date D cannot exit on date D—this prevents artificial same-candle fills and matches real trading behavior (hold minimum 1 day).

### No Lookahead
In `generate` mode, each week's strategy receives only candles **before** week-start. This prevents accidentally using future data in the recommendation.

### Pending Entries Expire Weekly
Unfilled entries are cleared at week-end. Next Monday's plan starts fresh with new recommendations.

### Single Data Fetch
All symbols are fetched once (`from_date - 52 weeks → to_date`) instead of per-week, avoiding repeated API calls.

### Auto-Fallback Provider
If vnstock init fails (e.g., pandas not installed), automatically builds http → cache chain so the CLI never hard-crashes.

### Range Simulation Efficiency
`--run-range` runs identical logic twice on the same pre-fetched data—the only difference is tie-breaker mode. No extra API calls.

---

## Test Coverage

**33 unit tests** organized in 5 classes:

1. **TestEntryTouched** (7 tests)
   - Inside range, at boundaries, misses

2. **TestSLTPTouch** (6 tests)
   - SL/TP hit below/above, at exact level, misses

3. **TestSameDayTieBreaker** (3 tests)
   - worst → SL, best → TP, defaults

4. **TestPortfolioAccounting** (13 tests)
   - Qty calculation, insufficient cash, entry miss
   - TP/SL exit credits/debits
   - No same-day entry+exit
   - Same-day both (worst vs best)
   - Equity curve recording
   - Summary metrics (empty, with trades, win_rate, PF)
   - Invalid tie-breaker raises

5. **TestGetWeekStarts** (5 tests)
   - Monday start, mid-week start, single week, empty, spacing

**All 33 tests PASS.**
**All 105 existing tests still PASS (no regressions).**

---

## File Structure

```
/Users/khangdang/IndicatorK/
├── src/backtest/
│   ├── __init__.py
│   ├── engine.py              ← Core: touch logic, BacktestEngine
│   ├── weekly_generator.py    ← Week iteration, plan helpers
│   ├── reporter.py            ← Output writers (JSON, CSV)
│   ├── cli.py                 ← CLI + orchestration + provider fallback
│   └── __main__.py            ← python -m src.backtest entry
├── scripts/
│   └── backtest.py            ← Convenience wrapper
├── tests/
│   └── test_backtest.py       ← 33 unit tests
├── docs/
│   └── 10_BACKTEST_GUIDE.md   ← Full user guide
├── Makefile                   ← make backtest target
└── BACKTEST_IMPLEMENTATION.md ← This file
```

---

## Integration with Existing App

**No breaking changes.** The backtest module is:
- ✅ Completely isolated under `src/backtest/`
- ✅ Uses existing providers, strategies, config system (no rewrites)
- ✅ Does not modify `trades.csv`, `portfolio.csv`, or live state
- ✅ Independent test suite (33 tests)
- ✅ Optional Makefile target
- ✅ Existing alerts, bot, weekly workflows untouched

---

## Outputs Example

Single run with 0 trades (no data from providers):

```
reports/20260226_120437/
├── summary.json
│   {
│     "from_date": "2025-05-01",
│     "to_date": "2026-02-25",
│     "initial_cash": 10000000,
│     "final_value": 10000000.0,
│     "cagr": 0.0,
│     "max_drawdown": 0.0,
│     "win_rate": 0.0,
│     "avg_hold_days": 0.0,
│     "num_trades": 0,
│     "profit_factor": 0.0
│   }
├── equity_curve.csv          (date, total_value, cash, open_positions_value)
└── trades.csv                (symbol, entry_date, entry_price, exit_date, exit_price, reason, return_pct, pnl_vnd)
```

Range run (`--run-range`):

```
reports/20260226_120437/
├── summary_worst.json
├── summary_best.json
├── equity_curve_worst.csv
├── equity_curve_best.csv
├── trades_worst.csv
├── trades_best.csv
└── range_summary.json
    {
      "worst": { ... },
      "best": { ... },
      "best_minus_worst": {
        "final_value": 0.0,
        "cagr": 0.0,
        "max_drawdown": 0.0,
        "win_rate": 0.0,
        "num_trades": 0
      }
    }
```

---

## Next Steps (Optional)

1. **Populate price cache:** Run with `--mode plan` once you have `data/weekly_plan.json` populated
2. **Install vnstock:** `pip install pandas vnstock` for faster, more reliable data
3. **Generate real backtest:** After receiving actual OHLCV data, run with `--run-range` to evaluate both scenarios
4. **Iterate on strategy:** Use results to refine buy_zone, SL, TP levels in recommendation generation

---

## Compliance Checklist

✅ Entry rule: mid-zone = (buy_zone_low + buy_zone_high) / 2
✅ Entry condition: daily OHLC touch (low <= entry <= high)
✅ Exit condition: touch SL or TP (first wins)
✅ Same-day tie-breaker: worst (SL) or best (TP) only
✅ No 50/50 mode
✅ Fixed order-size: 1,000,000 VND
✅ Trades per week: configurable (default 4)
✅ Initial capital: 10,000,000 VND
✅ Universe: data/watchlist.txt (10 symbols)
✅ Date range: 2025-05-01 to 2026-02-25
✅ Outputs: summary.json, equity_curve.csv, trades.csv, range_summary.json
✅ CLI: `python scripts/backtest.py` + `--run-range`
✅ Makefile: `make backtest FROM=... TO=...`
✅ Unit tests: 33 tests, all passing
✅ No breaking changes to existing app

---

## Files Created/Modified

### Created
- `src/backtest/__init__.py`
- `src/backtest/engine.py`
- `src/backtest/weekly_generator.py`
- `src/backtest/reporter.py`
- `src/backtest/cli.py`
- `src/backtest/__main__.py`
- `scripts/backtest.py`
- `tests/test_backtest.py`
- `docs/10_BACKTEST_GUIDE.md`
- `BACKTEST_IMPLEMENTATION.md` (this file)

### Modified
- `Makefile` — added `backtest` target

### Untouched
- All live trading code (alerts, bot, weekly workflows)
- All existing tests (0 failures, 105 passing)
- All provider implementations
- All strategy implementations

---

## Support

See [docs/10_BACKTEST_GUIDE.md](docs/10_BACKTEST_GUIDE.md) for:
- Full usage guide
- Entry/exit rule details
- Mode explanations
- Output format specification
- Examples and troubleshooting
- Integration notes
