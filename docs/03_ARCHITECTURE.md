# IndicatorK Project Summary

## Overview

**Vietnamese Personal Finance Assistant** - A zero-cost, zero-LLM bot that generates weekly trading plans and sends price alerts via Telegram, running entirely on GitHub Actions.

**Status**: ✅ **COMPLETE & TESTED** - 101/101 unit tests passing

---

## What Was Built

### Core Application (18 modules, 4500+ lines)

#### 1. Data Models (`src/models.py`)
- OHLCV (candlestick data)
- TradeRecord, Position, Portfolio
- WeeklyPlan, Recommendation
- GuardrailsReport with health metrics
- 10+ dataclasses for type safety

#### 2. Providers Layer (`src/providers/`)
- **PriceProvider ABC** - interface for all data sources
- **VnstockProvider** - Vietnamese stock data (guest mode, no API key)
- **HttpProvider** - Simplize API (free, no auth)
- **CacheProvider** - JSON file fallback
- **CompositeProvider** - automatic fallback chain with health tracking

#### 3. Strategies Layer (`src/strategies/`)
- **Strategy ABC** - base interface
- **TrendMomentumATR** - MA10w/MA30w trend + RSI + ATR stops (trend-following)
- **Rebalance5050** - allocation-first 50/50 stock/bond with drift thresholds

#### 4. Portfolio Engine (`src/portfolio/engine.py`)
- Parse trades.csv with validation
- FIFO position tracking
- Weighted average cost basis
- Realized/unrealized PnL
- Allocation computation (stock %, bond %, cash %)
- **Portfolio snapshots** for weekly tracking

#### 5. Guardrails Engine (`src/guardrails/engine.py`)
- Data quality checks (error rate, missing rate, stale data)
- Performance metrics (rolling 12-week CAGR, max drawdown, turnover)
- Automatic recommendations (SWITCH_PROVIDER, SWITCH_STRATEGY, DE_RISK)
- Structured JSON output

#### 6. Telegram Layer (`src/telegram/`)
- **Bot** - 24/7 long-polling with idempotency
- **Commands** - /buy, /sell, /setcash, /status, /plan, /help
- **Alerts** - buy zones, stop loss, take profit with dedup logic
- **Formatter** - hardcoded templates (no LLM), Markdown formatting

#### 7. Utilities (`src/utils/`)
- **Config** - YAML loading + provider/strategy factory (config-driven switching)
- **TradingHours** - Vietnam market hours (Mon-Fri 9-15 ICT) with early exit gate
- **CsvSafety** - Symbol validation + CSV injection prevention
- **Logging** - Structured logging with timestamps

### Configuration Files (3 YAML)

| File | Purpose | User-Editable |
|------|---------|---|
| `config/providers.yml` | Data source selection (primary/secondary/cache) | ✅ Yes |
| `config/strategy.yml` | Strategy selection + parameters | ✅ Yes |
| `config/risk.yml` | Risk thresholds for guardrails | ✅ Yes |

### Data Files (7 tracked + 2 auto-generated)

| File | Purpose | Updated By |
|------|---------|---|
| `data/trades.csv` | Trade log (user actions) | Bot commands |
| `data/watchlist.txt` | Symbol universe | Manual edit |
| `data/weekly_plan.json` | Current trading plan | Weekly workflow |
| `data/guardrails_report.json` | Health report | Weekly workflow |
| `data/portfolio_weekly.csv` | Value snapshots | Weekly workflow |
| `data/alerts_state.json` | Alert dedup state | 5-min alerts |
| `data/bot_state.json` | Last Telegram update ID | Bot polling |
| `data/prices_cache.json` | Cached prices (fallback) | Weekly workflow |

### GitHub Actions Workflows (3 automated)

| Workflow | Schedule | Commits Only If | Purpose |
|----------|----------|---|---|
| **alerts.yml** | Every 5 min, Mon-Fri 9-15 ICT | alerts_state.json changes | Price alerts |
| **weekly.yml** | Sunday 10:00 ICT | Any plan/snapshot/guardrails changes | Generate plan + guardrails |
| **bot.yml** | Every 5 min, 24/7 | trades.csv or bot_state.json changes | Command polling |

**Optimization**: No empty commits. Each workflow checks `git diff --staged --quiet` before committing.

### Test Suite (7 test files, 101 tests)

| Test File | Coverage |
|---|---|
| `test_alert_dedup.py` | Zone entry/exit, 24h re-alert, state persistence |
| `test_commands.py` | /buy, /sell, /setcash parsing and validation |
| `test_csv_safety.py` | Symbol validation, CSV injection prevention |
| `test_portfolio.py` | Position calc, PnL, allocation, snapshots |
| `test_providers.py` | Composite fallback chain, config-driven selection |
| `test_strategies.py` | Plan schema validation, strategy selection |
| `test_trading_hours.py` | Vietnam TZ, weekends, lunch break, UTC conversion |

**All 101 tests pass** ✅

### Documentation (6 files)

| File | Purpose |
|---|---|
| `README.md` | Architecture, feature overview, risk disclaimer |
| `PLAN.md` | Implementation plan (12 phases) |
| `DEPLOY.md` | Complete deployment guide with troubleshooting |
| `SETUP.md` | Detailed technical setup |
| `START_HERE.md` | Quick 5-step deployment |
| `CHECKLIST.txt` | Printable deployment checklist |

### Build Files

- `requirements.txt` - Core dependencies (requests, PyYAML, pytz, pytest)
- `Makefile` - Commands (setup, test, run_weekly_once, run_alerts_once, run_bot_once)

---

## Architecture Highlights

### 1. Modularity & Config-Driven Design

**Before**: To switch providers or strategies, you'd edit Python code.  
**After**: Edit a YAML file, no code changes needed.

```yaml
# config/providers.yml
primary: vnstock       # swap to: http or cache
secondary: http

# config/strategy.yml
active: trend_momentum_atr    # swap to: rebalance_50_50
```

### 2. Provider Fallback Chain

```
Primary (vnstock) → Secondary (HTTP) → Cache → Empty result
↓ fails              ↓ fails             ↓ fails    ↓
Use cache if primary fails, notify in guardrails
```

### 3. Trading Hours Gate

```
alerts.yml invoked every 5 min
→ is_trading_hours() check
  → Outside hours? EXIT immediately (no network calls)
  → Trading hours? Continue → fetch prices → check alerts → send Telegram
```

Saves bandwidth and prevents unnecessary API calls.

### 4. Guardrails Monitoring

Automatically tracks:
- **Data quality** - error rate, missing rate per provider
- **Performance** - rolling CAGR, max drawdown, turnover
- **Recommendations** - triggered when thresholds exceeded

Example: If error rate > 30%, recommends `SWITCH_PROVIDER to http`

### 5. Portfolio Snapshots for Fast Metrics

Instead of recalculating portfolio value from scratch each week:
```
data/portfolio_weekly.csv
date_iso,total_value,stock_value,bond_fund_value,cash_value,realized_pnl,unrealized_pnl
2025-01-01,10000000,6000000,2500000,1500000,50000,75000
```

Guardrails then computes CAGR from these snapshots (O(n) instead of O(trade_count)).

### 6. Alert Deduplication

Prevents spam:
- Track `inside_zone` state per (symbol, alert_type)
- Only alert on **entry** (wasn't inside → now inside)
- Re-alert after **24 hours** if still inside
- Exit triggers no alert

---

## Zero-Cost Guarantee

| Component | Cost |
|---|---|
| GitHub Actions | $0 (free for public repos) |
| vnstock library | $0 (guest mode, no API key) |
| Simplize API | $0 (free public endpoint) |
| Telegram Bot API | $0 (unlimited for bots) |
| LLM calls | $0 (zero LLM design) |
| **TOTAL** | **$0** |

---

## Key Metrics

| Metric | Value |
|---|---|
| Lines of Code | 4500+ |
| Python Modules | 18 |
| Unit Tests | 101 |
| Test Pass Rate | 100% ✅ |
| Type Hints | Full coverage |
| Config Files | 3 (all user-editable) |
| Documentation | 6 comprehensive guides |
| Workflow Automation | 3 (zero manual intervention) |
| Guardrail Checks | Data quality + Performance |

---

## Deployment Checklist

- ✅ Code written & tested
- ✅ 101 unit tests passing
- ✅ GitHub Actions workflows ready
- ✅ Documentation complete
- ✅ Deployment guides included
- ⏳ Ready for your Telegram credentials
- ⏳ Ready for GitHub push

---

## Next Steps for User

1. **5 min**: Create Telegram bot with @BotFather
2. **10 min**: Test locally (make test, make run_weekly_once)
3. **10 min**: Push to GitHub and add secrets
4. **5 min**: Verify workflows run
5. **Done!** Bot runs automatically forever, $0 cost

See [START_HERE.md](START_HERE.md) to begin!

---

## File Listing (57 files total)

```
IndicatorK/
├── .github/workflows/ (3 files)
├── config/ (3 files)
├── data/ (8 files)
├── scripts/ (3 files)
├── src/ (18 files)
│   ├── providers/ (5 files)
│   ├── strategies/ (3 files)
│   ├── telegram/ (4 files)
│   ├── guardrails/ (1 file)
│   ├── portfolio/ (1 file)
│   └── utils/ (4 files)
├── tests/ (8 files)
├── Documentation (6 files)
└── Build files (3 files)
```

---

## Production Ready

✅ Error handling & logging  
✅ CSV injection prevention  
✅ Symbol validation  
✅ Idempotency (no double-processing)  
✅ Rate limiting & retries  
✅ Git diff checking (no empty commits)  
✅ Type hints throughout  
✅ Comprehensive tests  
✅ Concurrency controls on GitHub Actions  

---

**Status**: Ready for deployment! 🚀
