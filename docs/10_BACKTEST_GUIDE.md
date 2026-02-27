# Backtest Guide

## Overview

The backtest module simulates the weekly trading strategy on historical OHLCV data from **2025-05-01 to 2026-02-25**.

- **Purpose:** Evaluate strategy performance independently of manual trades.csv
- **Data:** Reuses existing providers (vnstock, http, cache)
- **Capital:** 10,000,000 VND initial; 1,000,000 VND per trade
- **Trades/week:** Configurable (default 4)
- **Universe:** 10 symbols from data/watchlist.txt (HPG, VNM, FPT, MWG, VCB, TCB, MBB, VHM, VIC, SSI)

---

## Entry / Exit Rules

### Entry
- Entry price = **mid-zone** = (buy_zone_low + buy_zone_high) / 2
- Entry occurs when daily OHLC **touches** the entry: `low <= entry <= high`
- Max 4 new entries per week (configurable)
- Entries expire at week-end if unfilled

### Exit
- Exit triggers when **first** of SL or TP is touched:
  - SL touched: `day_low <= stop_loss`
  - TP touched: `day_high >= take_profit`
- **Same-day SL+TP** (both touched on same day):
  - `--tie-breaker worst` → assume SL first
  - `--tie-breaker best` → assume TP first
  - Default: `worst`

### No Same-Day Entry+Exit
- If entry fills on date D, exit cannot occur on date D (realistic holding)
- Exit first becomes eligible on date D+1

---

## Modes

### generate (default)
- Each week, uses the active strategy to generate recommendations
- Only uses OHLCV data **before** week-start (strict no-lookahead)
- Respects buy_zone_low/high, stop_loss, take_profit from recommendations
- Simulates entering up to `--trades-per-week` symbols

### plan
- Reuses a static `--plan-file` (default: data/weekly_plan.json) for all weeks
- Useful for offline testing / debugging without re-fetching data each week
- Much faster on repeated runs

---

## Usage

### Command Line

```bash
# Single run (worst tie-breaker)
python scripts/backtest.py \
  --from 2025-05-01 \
  --to 2026-02-25 \
  --initial-cash 10000000 \
  --order-size 1000000 \
  --trades-per-week 4 \
  --mode generate

# Range: both worst and best
python scripts/backtest.py \
  --from 2025-05-01 \
  --to 2026-02-25 \
  --run-range

# Via module
python -m src.backtest \
  --from 2025-05-01 \
  --to 2026-02-25 \
  --run-range
```

### Makefile

```bash
# Recommended: spec-matched defaults
make backtest FROM=2025-05-01 TO=2026-02-25 RUN_RANGE=1

# Custom order size
make backtest FROM=2025-05-01 TO=2026-02-25 ORDER_SIZE=500000

# Custom trades per week
make backtest FROM=2025-05-01 TO=2026-02-25 TRADES_PER_WEEK=2

# Use static plan (fast)
make backtest FROM=2025-05-01 TO=2026-02-25 MODE=plan RUN_RANGE=1
```

### Full CLI Spec

```
python scripts/backtest.py --help

optional arguments:
  --from YYYY-MM-DD        Backtest start date [required]
  --to YYYY-MM-DD          Backtest end date [required]
  --initial-cash INTEGER   Starting cash in VND (default: 10000000)
  --order-size INTEGER     Fixed VND per trade (default: 1000000)
  --trades-per-week INT    Max new positions/week (default: 4)
  --universe PATH          Watchlist file (default: data/watchlist.txt)
  --mode CHOICE            'generate' or 'plan' (default: generate)
  --plan-file PATH         Plan JSON for --mode plan (default: data/weekly_plan.json)
  --tie-breaker CHOICE     'worst' or 'best' (default: worst)
  --run-range              Run both worst+best; outputs range_summary.json
```

---

## Outputs

Results are written to `reports/<YYYYMMDD_HHMMSS>/`.

### Single Run (default worst or custom --tie-breaker)
- `summary.json` — metrics snapshot
- `equity_curve.csv` — date, total_value, cash, open_positions_value
- `trades.csv` — symbol, entry_date, entry_price, exit_date, exit_price, reason, return_pct, pnl_vnd

### Range Run (--run-range)
- `summary_worst.json` + `summary_best.json`
- `equity_curve_worst.csv` + `equity_curve_best.csv`
- `trades_worst.csv` + `trades_best.csv`
- `range_summary.json` — comparison of worst vs best

### Summary JSON Structure
```json
{
  "from_date": "2025-05-01",
  "to_date": "2026-02-25",
  "initial_cash": 10000000,
  "final_value": 10500000,
  "cagr": 0.0532,
  "max_drawdown": 0.1234,
  "win_rate": 0.6250,
  "avg_hold_days": 8.33,
  "num_trades": 16,
  "profit_factor": 2.5
}
```

### Trades CSV Structure
```csv
symbol,entry_date,entry_price,exit_date,exit_price,reason,return_pct,pnl_vnd
HPG,2025-05-05,29000,2025-05-12,30145,TP,4.6379,324000
VNM,2025-05-06,84500,2025-05-20,81120,SL,-4.0071,-266100
```

### Range Summary Structure
```json
{
  "worst": { ... },
  "best": { ... },
  "best_minus_worst": {
    "final_value": 250000,
    "cagr": 0.0112,
    "max_drawdown": -0.0200,
    "win_rate": 0.1250,
    "num_trades": 0
  }
}
```

---

## Data Sources

The backtest reuses the provider chain from config/providers.yml:

1. **Primary (vnstock)**
   - Vietnamese stock data (VCI source)
   - Guest mode (no auth required)
   - Requires: `pip install pandas vnstock`
   - Fallback: automatic if pandas not installed

2. **Secondary (http)**
   - Simplize API (public)
   - Used if vnstock fails
   - Base URL: https://api.simplize.vn/api/company/get-chart

3. **Cache (file)**
   - JSON persistence layer
   - Path: data/prices_cache.json
   - Speeds up repeated runs

**Auto-fallback:** If vnstock init fails, the CLI automatically builds http → cache chain so the backtest never crashes on missing dependencies.

---

## Portfolio Accounting

### Fixed Order-Size Model
- Each entry: `qty = floor(order_size / entry_price)`
- Example: 1,000,000 VND ÷ 29,000 = 34 shares @ 29,000
- Cost = 34 × 29,000 = 986,000 VND deducted from cash

### Position Tracking
- All open trades tracked by symbol, entry_date, entry_price, SL, TP
- Equity curve computed daily: `total = cash + sum(open_positions_value)`
- Open position value: current_qty × last_close_price (from daily candle)

### Exit Settlement
- SL exit: proceeds = qty × stop_loss → cash credited
- TP exit: proceeds = qty × take_profit → cash credited
- PnL = proceeds − cost_vnd (recorded in closed_trades)

### Summary Metrics
- **CAGR:** Compound annual growth rate over backtest period
- **Max Drawdown:** Largest peak-to-trough decline
- **Win Rate:** Fraction of closed trades with pnl_vnd > 0
- **Avg Hold Days:** Average holding period
- **Profit Factor:** Gross profit ÷ Gross loss
- **Num Trades:** Total closed trades

---

## Tests

33 unit tests cover:

### Core Touch Logic (7 tests)
- entry_touched: inside, at boundaries, miss
- sl_touched: hit below, at, miss above
- tp_touched: hit above, at, miss below

### Tie-Breaker Logic (3 tests)
- resolve_same_day for worst (SL first)
- resolve_same_day for best (TP first)

### Portfolio Accounting (13 tests)
- Qty calculation (floor of order_size / entry)
- Insufficient cash blocks entry
- Entry not triggered if price misses
- TP/SL exit credits/debits cash
- No same-day entry+exit
- Same-day both SL+TP (worst vs best modes)
- Equity curve recorded daily
- Summary metrics (zero trades, win rate, PF)
- Invalid tie-breaker raises error

### Week Helpers (5 tests)
- get_week_starts from Monday
- Mid-week start yields same week Monday
- Single week range
- Empty range (from > to)
- Weekly spacing (7 days apart)

**Run tests:**
```bash
pytest tests/test_backtest.py -v
```

---

## Examples

### Example 1: Full Range (2025-05-01 to 2026-02-25)

```bash
make backtest FROM=2025-05-01 TO=2026-02-25 RUN_RANGE=1
```

Output:
```
reports/20260226_153000/
├── summary_worst.json
├── summary_best.json
├── equity_curve_worst.csv
├── equity_curve_best.csv
├── trades_worst.csv
├── trades_best.csv
└── range_summary.json
```

### Example 2: Single Worst-Case Run

```bash
python scripts/backtest.py \
  --from 2025-05-01 \
  --to 2026-02-25 \
  --initial-cash 10000000 \
  --order-size 1000000 \
  --trades-per-week 4 \
  --tie-breaker worst
```

Output:
```
reports/20260226_154000/
├── summary.json
├── equity_curve.csv
└── trades.csv
```

### Example 3: Plan Mode (Offline Testing)

1. Generate a static plan once:
   ```bash
   python scripts/run_weekly.py  # writes data/weekly_plan.json
   ```

2. Backtest with that plan (no strategy re-computation):
   ```bash
   make backtest FROM=2025-05-01 TO=2026-02-25 MODE=plan RUN_RANGE=1
   ```

---

## Interpretation

### Positive Indicators
- **CAGR > 9%** (benchmark)
- **Max Drawdown < 15%** (risk guardrail)
- **Win Rate > 50%** (more wins than losses)
- **Profit Factor > 1.0** (gross profit > gross loss)

### Red Flags
- **Equity curve flat or declining** → strategy not working
- **Max Drawdown > 20%** → unacceptable risk
- **Profit Factor < 1.0** → losing money overall
- **Very few trades** → data issue or plan too conservative

### Tie-Breaker Comparison (--run-range)
- **Best > Worst?** → Optimistic scenario better
- **Difference > 5% CAGR?** → Tie-breaker has material impact
- **Both underwater?** → Strategy issue, not tie-breaker

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `ImportError: pandas` | Run `pip install pandas vnstock` or use cache + http |
| `404 errors from Simplize API` | Check internet; may require auth token or be down |
| `No market data before <date>` | Reduce --trades-per-week or start later (need 52 weeks history) |
| Empty results / 0 trades | Check universe file; ensure symbols exist in provider |
| Very slow run | Use `--mode plan` for offline testing or reduce date range |

---

## Integration with Live Trading

The backtest is **independent** from live trading (trades.csv, portfolio.csv):

- Backtest = simulation of recommendations on historical data
- Live = actual executed trades
- Use backtest to validate strategy rules before deploying live
- If backtest fails, reconsider entry/exit rules before going live
- If backtest succeeds but live underperforms, check for slippage, fees, execution delays

---

## References

- **Entry/Exit Logic:** [src/backtest/engine.py](../src/backtest/engine.py)
- **CLI & Orchestration:** [src/backtest/cli.py](../src/backtest/cli.py)
- **Weekly Generation:** [src/backtest/weekly_generator.py](../src/backtest/weekly_generator.py)
- **Reporting:** [src/backtest/reporter.py](../src/backtest/reporter.py)
- **Tests:** [tests/test_backtest.py](../tests/test_backtest.py)
- **Makefile:** [Makefile](../Makefile) (target: `backtest`)
