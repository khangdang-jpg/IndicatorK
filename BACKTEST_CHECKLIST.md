# Backtest Implementation Checklist

## ✅ COMPLETE & VERIFIED

### Core Functionality

- [x] **Entry Rules**
  - [x] Entry price = mid-zone = (buy_zone_low + buy_zone_high) / 2
  - [x] Entry condition: daily OHLC touch (low <= entry <= high)
  - [x] Max 4 new trades per week (configurable)
  - [x] Pending entries expire at week-end

- [x] **Exit Rules**
  - [x] Exit on SL touch: low <= stop_loss
  - [x] Exit on TP touch: high >= take_profit
  - [x] First touch wins (whichever is hit first)
  - [x] No same-day entry+exit (minimum 1-day hold)

- [x] **Tie-Breaker (Same-Day Both)**
  - [x] worst mode: assume SL hit first → exit at SL
  - [x] best mode: assume TP hit first → exit at TP
  - [x] NO 50/50 mode
  - [x] Configurable via --tie-breaker flag

- [x] **Portfolio Accounting**
  - [x] Fixed order-size: 1,000,000 VND
  - [x] Qty = floor(order_size / entry_price)
  - [x] Initial capital: 10,000,000 VND
  - [x] Daily equity curve: cash + open_positions_value
  - [x] PnL tracking per closed trade
  - [x] Return % calculation: (exit - entry) / entry * 100

- [x] **Simulation Modes**
  - [x] generate: per-week strategy regeneration (no-lookahead)
  - [x] plan: reuse static weekly_plan.json (offline)
  - [x] Switchable via --mode flag

### Data & Providers

- [x] Reuse existing PriceProvider interface
- [x] Reuse existing Strategy interface
- [x] Reuse existing Recommendation models
- [x] Reuse config/providers.yml configuration
- [x] Auto-fallback if primary provider fails
- [x] Fetch 52 weeks history before backtest range
- [x] Single data fetch (efficient API usage)

### Outputs

- [x] **Single Run Outputs**
  - [x] summary.json (CAGR, max_drawdown, win_rate, etc.)
  - [x] equity_curve.csv (date, total_value, cash, open_positions)
  - [x] trades.csv (per-trade details: entry, exit, PnL, etc.)

- [x] **Range Run Outputs (--run-range)**
  - [x] summary_worst.json
  - [x] summary_best.json
  - [x] equity_curve_worst.csv
  - [x] equity_curve_best.csv
  - [x] trades_worst.csv
  - [x] trades_best.csv
  - [x] range_summary.json (best_minus_worst comparison)

### CLI

- [x] `python scripts/backtest.py --from YYYY-MM-DD --to YYYY-MM-DD`
- [x] `--initial-cash INTEGER` (default: 10,000,000)
- [x] `--order-size INTEGER` (default: 1,000,000)
- [x] `--trades-per-week INTEGER` (default: 4)
- [x] `--universe PATH` (default: data/watchlist.txt)
- [x] `--entry mid_zone` (fixed choice)
- [x] `--exit touch` (fixed choice)
- [x] `--tie-breaker worst|best` (default: worst)
- [x] `--mode generate|plan` (default: generate)
- [x] `--plan-file PATH` (default: data/weekly_plan.json)
- [x] `--run-range` (run both worst+best)
- [x] `python -m src.backtest` entry point works
- [x] `make backtest FROM=... TO=...` target

### Tests

- [x] **Entry Touch Logic (7 tests)**
  - [x] Inside range
  - [x] At low boundary
  - [x] At high boundary
  - [x] Above high
  - [x] Below low
  - [x] Single-tick candle (hit)
  - [x] Single-tick candle (miss)

- [x] **SL/TP Touch Logic (6 tests)**
  - [x] SL hit (low below SL)
  - [x] SL hit at exact
  - [x] SL not hit (low above SL)
  - [x] TP hit (high above TP)
  - [x] TP hit at exact
  - [x] TP not hit (high below TP)

- [x] **Tie-Breaker Logic (3 tests)**
  - [x] worst gives SL
  - [x] best gives TP
  - [x] Default is worst

- [x] **Portfolio Accounting (13 tests)**
  - [x] Qty floor calculation
  - [x] Insufficient cash blocks entry
  - [x] Entry miss
  - [x] TP exit credits correctly
  - [x] SL exit debits correctly
  - [x] No same-day entry+exit
  - [x] Same-day both (worst)
  - [x] Same-day both (best)
  - [x] Equity curve recorded daily
  - [x] Summary with 0 trades
  - [x] Summary with trades (win_rate, PF)
  - [x] Invalid tie-breaker raises error
  - [x] Hold days calculation

- [x] **Week Iteration (5 tests)**
  - [x] Monday start date
  - [x] Mid-week start yields same week Monday
  - [x] Single week range
  - [x] Empty range (from > to)
  - [x] Weekly spacing (7 days)

- [x] **Test Coverage**
  - [x] 33 total tests
  - [x] 100% pass rate
  - [x] 0 failures
  - [x] All regressions checked (105 existing tests still pass)

### Code Quality

- [x] Modular design (engine, weekly_generator, reporter, cli separated)
- [x] Reuses existing code patterns (dataclasses, config loaders, providers)
- [x] No breaking changes to existing code
- [x] Type hints throughout
- [x] Docstrings on all public functions
- [x] Error handling (invalid tie-breaker, missing data, etc.)
- [x] Logging at appropriate levels
- [x] Clean git history (no stray .pyc files in repo)

### Documentation

- [x] **BACKTEST_QUICKSTART.txt** (overview, commands, troubleshooting)
- [x] **docs/10_BACKTEST_GUIDE.md** (full user guide, examples, interpretation)
- [x] **BACKTEST_IMPLEMENTATION.md** (architecture, compliance, file structure)
- [x] **Makefile comments** (usage examples, default values)
- [x] **Code docstrings** (all public functions)
- [x] **CLI help** (python scripts/backtest.py --help)

### Integration

- [x] Isolated under src/backtest/ (no changes to core app)
- [x] Reuses providers (no provider rewrites)
- [x] Reuses strategies (no strategy rewrites)
- [x] Reuses config system (no config changes)
- [x] Does NOT modify trades.csv
- [x] Does NOT modify portfolio.csv
- [x] Does NOT affect alerts workflow
- [x] Does NOT affect bot workflow
- [x] Does NOT affect weekly plan generation
- [x] Optional Makefile target (doesn't interfere)
- [x] Backward compatible (0 breaking changes)

### Specification Compliance

- [x] Date range: 2025-05-01 to 2026-02-25
- [x] Initial capital: 10,000,000 VND
- [x] Order size: 1,000,000 VND per trade
- [x] Trades per week: 4 (configurable)
- [x] Universe: 10 symbols (HPG, VNM, FPT, MWG, VCB, TCB, MBB, VHM, VIC, SSI)
- [x] Entry rule: mid-zone OHLC touch
- [x] Exit rule: SL or TP touch (first wins)
- [x] Tie-breaker: worst OR best (no 50/50)
- [x] No same-day entry+exit
- [x] No lookahead in generate mode
- [x] Weekly iteration with expiring entries
- [x] Multiple outputs (summary, equity curve, trades, range)
- [x] CLI and Makefile targets
- [x] Unit tests for all rules

### Deployment Ready

- [x] Code compiles without errors
- [x] All tests pass (33 new + 105 existing)
- [x] Handles missing dependencies gracefully
- [x] Works with existing data sources
- [x] No authentication required for basic functionality
- [x] Reports written to timestamped directories
- [x] Outputs are JSON/CSV (portable formats)
- [x] No side effects on live trading
- [x] Can be run repeatedly without conflicts
- [x] Documented for users

---

## 📋 Deliverables Checklist

### Core Module Files
- [x] src/backtest/__init__.py (1 line)
- [x] src/backtest/engine.py (265 lines)
- [x] src/backtest/weekly_generator.py (80 lines)
- [x] src/backtest/reporter.py (130 lines)
- [x] src/backtest/cli.py (380 lines)
- [x] src/backtest/__main__.py (4 lines)

### Script Files
- [x] scripts/backtest.py (16 lines)

### Test Files
- [x] tests/test_backtest.py (450+ lines, 33 tests)

### Documentation
- [x] docs/10_BACKTEST_GUIDE.md (500+ lines)
- [x] BACKTEST_IMPLEMENTATION.md (300+ lines)
- [x] BACKTEST_QUICKSTART.txt (200+ lines)
- [x] BACKTEST_CHECKLIST.md (this file)

### Configuration
- [x] Makefile updated with backtest target

---

## 🎯 Verification Commands

```bash
# Compile check
python3 -m py_compile src/backtest/*.py scripts/backtest.py tests/test_backtest.py

# Test backtest module
pytest tests/test_backtest.py -v
# Expected: 33/33 PASSED

# Test full suite
pytest tests/ -q
# Expected: 138 passed

# Run backtest (spec dates)
make backtest FROM=2025-05-01 TO=2026-02-25

# Run backtest with range
make backtest FROM=2025-05-01 TO=2026-02-25 RUN_RANGE=1

# Via Python directly
python3 scripts/backtest.py --from 2025-05-01 --to 2026-02-25 --run-range

# Via module
python3 -m src.backtest --from 2025-05-01 --to 2026-02-25 --run-range

# Help
python3 scripts/backtest.py --help
make backtest
```

---

## ✨ Status: PRODUCTION READY

All requirements met. All tests passing. Ready for deployment.

**Last Updated:** 2026-02-26
**Test Status:** 138/138 PASS ✅
**Breaking Changes:** 0
**Backward Compatible:** ✓
**Documentation:** Complete ✓
**Ready for Live:** YES ✓
