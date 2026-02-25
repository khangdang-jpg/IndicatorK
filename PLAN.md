# Vietnamese Personal Finance Assistant — Implementation Plan

## Context

Build a zero-cost, zero-LLM personal finance MVP for the Vietnamese market. The system generates weekly trading plans and sends near-realtime (5-min) alerts via Telegram, running entirely on GitHub Actions cron schedules in a public repo. All behavior is config-driven so data sources and strategies can be swapped without code changes. Guardrails monitor data quality and strategy performance, recommending corrective actions automatically.

---

## File Tree

```
IndicatorK/
├── .github/
│   └── workflows/
│       ├── alerts.yml          # 5-min alert checks during trading hours
│       ├── weekly.yml          # Weekly plan generation (Sunday 10:00 ICT)
│       └── bot.yml             # Telegram bot long-poll (5-min, 24/7)
├── config/
│   ├── providers.yml           # Data source selection & params
│   ├── strategy.yml            # Active strategy selection & params
│   └── risk.yml                # Risk parameters & guardrail thresholds
├── data/
│   ├── trades.csv              # Portfolio trade log (header + sample)
│   ├── watchlist.txt           # Universe symbols (one per line)
│   ├── weekly_plan.json        # Latest generated plan
│   ├── alerts_state.json       # Alert dedup state
│   ├── prices_cache.json       # Cached price data
│   ├── bot_state.json          # Telegram bot last_update_id
│   └── guardrails_report.json  # Latest guardrails output
├── src/
│   ├── __init__.py
│   ├── models.py               # Shared dataclasses (OHLCV, WeeklyPlan, Position, etc.)
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py             # PriceProvider ABC
│   │   ├── vnstock_provider.py # vnstock library wrapper
│   │   ├── http_provider.py    # Public HTTP endpoint fetcher (Simplize API)
│   │   ├── cache_provider.py   # JSON file cache read/write
│   │   └── composite_provider.py # Fallback chain: primary → secondary → cache
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── base.py             # Strategy ABC
│   │   ├── trend_momentum_atr.py  # S1: trend + momentum + ATR stops
│   │   └── rebalance_50_50.py     # S2: allocation-first 50/50 rebalance
│   ├── guardrails/
│   │   ├── __init__.py
│   │   └── engine.py           # Data quality + performance checks → JSON report
│   ├── portfolio/
│   │   ├── __init__.py
│   │   └── engine.py           # Parse trades.csv, compute positions, PnL, allocation
│   ├── telegram/
│   │   ├── __init__.py
│   │   ├── bot.py              # Long-poll getUpdates, command routing, admin gate
│   │   ├── commands.py         # Command parsers (/buy, /sell, /setcash, /status, /plan, /help)
│   │   ├── alerts.py           # Alert checker + dedup logic
│   │   └── formatter.py        # Message templates (weekly digest, alerts, status)
│   └── utils/
│       ├── __init__.py
│       ├── config.py           # YAML config loader + provider/strategy factory
│       ├── trading_hours.py    # Vietnam trading hours gate (Asia/Ho_Chi_Minh)
│       ├── csv_safety.py       # Symbol validation + CSV injection prevention
│       └── logging_setup.py    # Structured logging config
├── scripts/
│   ├── run_alerts.py           # Entry point: alerts workflow
│   ├── run_weekly.py           # Entry point: weekly plan workflow
│   └── run_bot.py              # Entry point: telegram bot poll
├── tests/
│   ├── __init__.py
│   ├── test_commands.py        # Telegram command parsing
│   ├── test_portfolio.py       # Portfolio position/PnL calcs
│   ├── test_trading_hours.py   # Trading hours gate
│   ├── test_alert_dedup.py     # Alert deduplication logic
│   ├── test_providers.py       # Provider selection from config
│   ├── test_strategies.py      # Strategy selection from config
│   └── test_csv_safety.py      # Symbol validation + injection prevention
├── Makefile
├── requirements.txt
└── README.md
```

---

## Implementation Details

### Phase 1: Core Models & Utilities

#### `src/models.py`
Shared dataclasses used across all modules:
- `OHLCV(date, open, high, low, close, volume)` — single candle
- `WeeklyPlan` — mirrors the weekly_plan.json schema exactly
- `Recommendation(symbol, asset_class, action, buy_zone_low, buy_zone_high, stop_loss, take_profit, position_target_pct, rationale_bullets)`
- `Position(symbol, asset_class, qty, avg_cost, current_price, unrealized_pnl, realized_pnl)`
- `TradeRecord(timestamp_iso, asset_class, symbol, side, qty, price, fee, note)` — one CSV row
- `GuardrailsReport(provider_health, strategy_health, recommendations)`

#### `src/utils/config.py`
- `load_yaml(path) -> dict` — safe YAML loader
- `get_provider(config_path="config/providers.yml") -> PriceProvider` — reads YAML, instantiates composite provider with configured primary/secondary/cache
- `get_strategy(config_path="config/strategy.yml") -> Strategy` — reads YAML, instantiates the named strategy with its params
- `get_risk_config(config_path="config/risk.yml") -> dict` — risk thresholds

#### `src/utils/trading_hours.py`
- `is_trading_hours(now=None) -> bool` — checks Asia/Ho_Chi_Minh TZ, Mon-Fri, 09:00-11:30 OR 13:00-15:00
- `get_vietnam_now() -> datetime` — current time in ICT

#### `src/utils/csv_safety.py`
- `validate_symbol(s: str) -> str` — uppercase, alphanumeric only, 1-10 chars, raises ValueError otherwise
- `sanitize_csv_field(s: str) -> str` — strip leading `=`, `+`, `-`, `@`, `\t`, `\r` to prevent CSV injection
- `parse_number(s: str) -> float` — safe numeric parse

#### `src/utils/logging_setup.py`
- `setup_logging(level="INFO")` — configures structured logging with timestamp, module, level
- Used by all entry scripts

---

### Phase 2: Provider Layer (`src/providers/`)

#### `src/providers/base.py`
```python
class PriceProvider(ABC):
    name: str
    @abstractmethod
    def get_last_prices(self, symbols: list[str]) -> dict[str, float]: ...
    @abstractmethod
    def get_daily_history(self, symbol: str, start: date, end: date) -> list[OHLCV]: ...
```

#### `src/providers/vnstock_provider.py`
- Wraps `vnstock` library (v3.x guest mode, no API key)
- `get_daily_history`: uses `Vnstock().stock(symbol=sym, source='VCI').quote.history(start, end)` → parse DataFrame → list[OHLCV]
- `get_last_prices`: calls `get_daily_history` for last 5 days, returns latest close
- Handles ImportError gracefully: if vnstock not installed, raises clear exception with install instructions
- Timeout: 30s per request, 3 retries with exponential backoff

#### `src/providers/http_provider.py`
- Fetches from Simplize public API (`https://api.simplize.vn/api/company/get-chart`)
- Uses `requests` with retries (urllib3 Retry adapter), 15s timeout
- Robust JSON parsing with error handling
- Raises clear error with instructions if endpoint changes

#### `src/providers/cache_provider.py`
- Reads/writes `data/prices_cache.json`
- Schema: `{"symbol": {"last_price": float, "updated_at": str, "history": {date_str: OHLCV_dict}}}`
- `get_last_prices`: returns cached prices (may be stale)
- `get_daily_history`: returns cached history
- `update_cache(symbol, price, history)` — called by composite after successful fetch

#### `src/providers/composite_provider.py`
- Constructed from config with `primary`, `secondary`, `cache` providers
- `get_last_prices`: try primary → if fails, try secondary → if fails, return cache
- `get_daily_history`: same fallback chain
- Logs which provider succeeded/failed
- Updates cache on any successful fetch
- Tracks error counts for guardrails (accessible via `get_health_stats()`)

> **Decision**: vnstock is primary (purpose-built, clean DataFrames), Simplize HTTP API is secondary fallback, cache is last resort.

---

### Phase 3: Strategy Layer (`src/strategies/`)

#### `src/strategies/base.py`
```python
class Strategy(ABC):
    @property
    @abstractmethod
    def id(self) -> str: ...
    @property
    @abstractmethod
    def version(self) -> str: ...
    @abstractmethod
    def generate_weekly_plan(self, market_data: dict, portfolio_state: dict, config: dict) -> WeeklyPlan: ...
```
- `market_data`: `{symbol: list[OHLCV]}` weekly candles
- `portfolio_state`: output of portfolio engine (positions, allocation, cash)
- `config`: risk params from risk.yml

#### `src/strategies/trend_momentum_atr.py` (S1)
- **id**: `"trend_momentum_atr"`, **version**: `"1.0.0"`
- Resample daily OHLCV → weekly candles
- Compute MA10w, MA30w (10-week and 30-week moving averages)
- Compute RSI(14) on weekly closes
- Compute ATR(14) on weekly candles
- Logic per symbol:
  - Trend UP: close > MA10w > MA30w
  - Trend DOWN: close < MA10w or MA10w < MA30w
  - Momentum: RSI > 50 = bullish, < 30 = oversold
  - BUY: trend UP + RSI not overbought → buy_zone = [close - 1*ATR, close - 0.5*ATR]
  - HOLD: already holding + trend UP
  - REDUCE: trend weakening (close < MA10w but > MA30w)
  - SELL: trend DOWN (close < MA30w) or stop_loss hit
  - stop_loss = buy_zone_low - 1.5*ATR
  - take_profit = close + 2*ATR
- Position sizing: equal-weight across BUY candidates, capped by stock allocation target

#### `src/strategies/rebalance_50_50.py` (S2)
- **id**: `"rebalance_50_50"`, **version**: `"1.0.0"`
- Target allocation: 50% stock, 50% bond+fund
- Compute current allocation from portfolio state
- If drift > threshold (default 5% from risk.yml):
  - Overweight stocks → REDUCE stock positions proportionally
  - Underweight stocks → BUY stock positions to fill
- Conservative zones: buy_zone = [close * 0.95, close * 0.98], stop_loss = close * 0.90, take_profit = close * 1.15
- Minimal trading: only generate actions when drift exceeds threshold
- For existing positions: HOLD unless rebalance needed

---

### Phase 4: Portfolio Engine (`src/portfolio/engine.py`)

- `load_trades(path="data/trades.csv") -> list[TradeRecord]` — parse CSV with validation
- `compute_positions(trades) -> dict[str, Position]` — FIFO avg cost basis
  - BUY: increase qty, update avg_cost weighted
  - SELL: decrease qty, compute realized PnL
  - CASH row: set cash balance
- `compute_allocation(positions, cash, current_prices) -> dict` — stock_pct, bond_fund_pct, cash_pct
- `get_portfolio_state(trades_path, provider) -> dict` — full state:
  - positions, cash, total_value, allocation, unrealized_pnl, realized_pnl
- Bond/fund price fallback: if provider returns nothing, use last trade price as current price

---

### Phase 5: Guardrails (`src/guardrails/engine.py`)

- `run_guardrails(provider, strategy_id, portfolio_state, weekly_plans_history, risk_config) -> GuardrailsReport`
- **Data quality checks**:
  - `missing_rate`: % of symbols where provider returned no price
  - `error_rate`: provider error count / total requests (from composite provider health stats)
  - `last_success_at`: timestamp of last successful fetch
  - Thresholds from risk.yml (e.g., error_rate > 0.3 → recommend SWITCH_PROVIDER)
- **Performance checks**:
  - Rolling 12-week portfolio value → compute CAGR
  - Compare vs benchmark (9%/year = ~0.17%/week)
  - Max drawdown from peak
  - Turnover: number of trades / portfolio size
  - Thresholds: CAGR < benchmark for 12 weeks → recommend SWITCH_STRATEGY; drawdown > threshold → recommend DE_RISK
- **Output**: write `data/guardrails_report.json` with structured schema
- **Recommendations**: list of action strings like `"SWITCH_PROVIDER to http"`, `"SWITCH_STRATEGY to rebalance_50_50"`, `"DE_RISK reduce targets"`

---

### Phase 6: Telegram Layer (`src/telegram/`)

#### `src/telegram/bot.py`
- `TelegramBot(token, admin_chat_id)`
- `get_updates(offset) -> list[Update]` — calls Telegram getUpdates API with timeout=30
- `send_message(chat_id, text, parse_mode="Markdown")` — calls sendMessage API
- `process_updates(updates)` — route to command handlers, admin gate check
- `run_once()` — single poll cycle (for cron usage): load bot_state.json → getUpdates → process → save bot_state.json

#### `src/telegram/commands.py`
- `parse_buy(text) -> TradeRecord` — parse `/buy SYMBOL QTY PRICE [asset=stock|bond|fund] [fee=N] [note=TEXT]`
- `parse_sell(text) -> TradeRecord` — same structure
- `parse_setcash(text) -> TradeRecord` — parse `/setcash AMOUNT`
- `handle_status(portfolio_state) -> str` — format current portfolio
- `handle_plan(weekly_plan) -> str` — format current plan summary
- `handle_help() -> str` — command reference
- All parsers use `csv_safety.validate_symbol()` and `csv_safety.parse_number()`
- Append trades to `data/trades.csv` using csv module (proper escaping)

#### `src/telegram/alerts.py`
- `check_alerts(weekly_plan, current_prices, alerts_state) -> list[Alert]`
- Alert types: `ENTERED_BUY_ZONE`, `STOP_LOSS_HIT`, `TAKE_PROFIT_HIT`
- Load `data/alerts_state.json`: `{"SYMBOL_ALERTTYPE": {"inside_zone": bool, "last_alerted_at": str}}`
- Dedup logic:
  - If price enters zone and was not `inside_zone` → alert + set inside_zone=True + set last_alerted_at
  - If was inside_zone and still inside → re-alert only if last_alerted_at > 24h ago
  - If price exits zone → set inside_zone=False (no alert)
- Save updated state back to `data/alerts_state.json`

#### `src/telegram/formatter.py`
- `format_weekly_digest(plan, portfolio_state, guardrails_report) -> str` — Markdown template:
  - Header with strategy ID and date
  - Top BUY candidates (max 10) with levels
  - Existing positions summary with actions
  - Allocation drift table
  - Guardrails warnings (if any)
- `format_alert(alert) -> str` — concise alert message
- `format_status(portfolio_state) -> str` — positions + allocation + PnL
- All templates are hardcoded strings with f-strings (no LLM)

---

### Phase 7: Entry Scripts (`scripts/`)

#### `scripts/run_alerts.py`
1. Setup logging
2. Check `is_trading_hours()` → exit early if outside hours
3. Load config, instantiate provider via `get_provider()`
4. Load `data/weekly_plan.json`
5. Load watchlist from `data/watchlist.txt`
6. Fetch current prices for all symbols in plan
7. Load `data/alerts_state.json`
8. Run `check_alerts()` → list of alerts
9. Send each alert via Telegram
10. Save updated `data/alerts_state.json`
11. Update `data/prices_cache.json`

#### `scripts/run_weekly.py`
1. Setup logging
2. Load config, provider, strategy, risk config
3. Load watchlist
4. Fetch daily history for all symbols (last 52 weeks)
5. Load trades, compute portfolio state
6. Call `strategy.generate_weekly_plan(market_data, portfolio_state, risk_config)`
7. Write `data/weekly_plan.json`
8. Run guardrails → write `data/guardrails_report.json`
9. Format weekly digest
10. Send via Telegram
11. Update prices cache

#### `scripts/run_bot.py`
1. Setup logging
2. No trading-hours gate — bot accepts commands 24/7
3. Load `data/bot_state.json` (last_update_id)
4. Poll Telegram getUpdates with offset = last_update_id + 1
5. Process each update (admin gate, command routing)
6. For trade commands: append to `data/trades.csv`
7. Save updated `data/bot_state.json`
8. Idempotency: skip updates with id <= last_update_id

---

### Phase 8: Config Files

#### `config/providers.yml`
```yaml
primary: vnstock       # vnstock | http | cache
secondary: http        # fallback if primary fails
cache_path: data/prices_cache.json
vnstock:
  source: VCI
  timeout: 30
http:
  base_url: "https://api.simplize.vn/api/company/get-chart"
  timeout: 15
  retries: 3
```
> **Decision**: vnstock is primary (purpose-built, clean DataFrames), Simplize HTTP API is secondary fallback, cache is last resort.

#### `config/strategy.yml`
```yaml
active: trend_momentum_atr   # trend_momentum_atr | rebalance_50_50
trend_momentum_atr:
  ma_short: 10
  ma_long: 30
  rsi_period: 14
  atr_period: 14
  atr_stop_mult: 1.5
  atr_target_mult: 2.0
rebalance_50_50:
  stock_target: 0.50
  bond_fund_target: 0.50
  drift_threshold: 0.05
```

#### `config/risk.yml`
```yaml
max_drawdown: 0.15
benchmark_cagr_annual: 0.09
rolling_weeks: 12
max_turnover_weekly: 0.20
guardrails:
  provider_error_rate_threshold: 0.30
  provider_missing_rate_threshold: 0.50
  min_cagr_vs_benchmark_ratio: 0.5
position:
  max_single_position_pct: 0.15
  max_stock_allocation: 0.60
```

---

### Phase 9: GitHub Actions Workflows

#### `.github/workflows/alerts.yml`
```yaml
name: Price Alerts
on:
  schedule:
    - cron: '*/5 2-8 * * 1-5'   # Every 5 min, UTC 2-8 ≈ ICT 9-15
  workflow_dispatch: {}
jobs:
  alerts:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r requirements.txt
      - run: python scripts/run_alerts.py
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_ADMIN_CHAT_ID: ${{ secrets.TELEGRAM_ADMIN_CHAT_ID }}
      - name: Commit state changes
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/alerts_state.json data/prices_cache.json
          git diff --staged --quiet || git commit -m "chore: update alerts state"
          git push
```

#### `.github/workflows/weekly.yml`
```yaml
name: Weekly Plan
on:
  schedule:
    - cron: '0 3 * * 0'   # Sunday 03:00 UTC = 10:00 ICT
  workflow_dispatch: {}
jobs:
  weekly:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r requirements.txt
      - run: python scripts/run_weekly.py
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_ADMIN_CHAT_ID: ${{ secrets.TELEGRAM_ADMIN_CHAT_ID }}
      - name: Commit outputs
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/weekly_plan.json data/guardrails_report.json data/prices_cache.json
          git diff --staged --quiet || git commit -m "chore: update weekly plan"
          git push
```

#### `.github/workflows/bot.yml`
```yaml
name: Telegram Bot
on:
  schedule:
    - cron: '*/5 * * * *'   # Every 5 min, 24/7 (commands work anytime)
  workflow_dispatch: {}
jobs:
  bot:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r requirements.txt
      - run: python scripts/run_bot.py
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_ADMIN_CHAT_ID: ${{ secrets.TELEGRAM_ADMIN_CHAT_ID }}
      - name: Commit state changes
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/trades.csv data/bot_state.json
          git diff --staged --quiet || git commit -m "chore: update bot state"
          git push
```
> **Decision**: Bot runs 24/7 so /status, /plan, /help, and trade logging work anytime. Only price alerts (alerts.yml) are gated to trading hours.

---

### Phase 10: Tests

All tests use `pytest` with no external dependencies beyond the project:

| Test file | What it covers |
|---|---|
| `test_commands.py` | Parse /buy, /sell, /setcash with valid/invalid inputs, optional params |
| `test_portfolio.py` | Position calc, avg cost, PnL, allocation ratios, CASH handling |
| `test_trading_hours.py` | Inside/outside hours, weekends, lunch break, timezone correctness |
| `test_alert_dedup.py` | Zone entry/exit, 24h re-alert, state persistence |
| `test_providers.py` | Config-driven provider selection, composite fallback chain (mocked) |
| `test_strategies.py` | Config-driven strategy selection, plan schema validation |
| `test_csv_safety.py` | Symbol validation (valid/invalid), CSV injection prevention |

---

### Phase 11: Makefile & requirements.txt

#### `requirements.txt`
```
vnstock>=3.0.0
requests>=2.31.0
PyYAML>=6.0
pytz>=2023.3
pytest>=7.0.0
```

#### `Makefile`
```makefile
setup:              pip install -r requirements.txt
test:               pytest tests/ -v
run_alerts_once:    python scripts/run_alerts.py
run_weekly_once:    python scripts/run_weekly.py
run_bot_once:       python scripts/run_bot.py
```

---

### Phase 12: Sample Data Files

- `data/trades.csv` — header row only: `timestamp_iso,asset_class,symbol,side,qty,price,fee,note`
- `data/watchlist.txt` — sample: HPG, VNM, FPT, MWG, VCB, TCB, MBB, VHM, VIC, SSI
- `data/weekly_plan.json` — sample with 2-3 recommendations matching schema
- `data/alerts_state.json` — empty: `{}`
- `data/prices_cache.json` — empty: `{}`
- `data/bot_state.json` — `{"last_update_id": 0}`
- `data/guardrails_report.json` — sample with empty recommendations

---

## Implementation Order

1. `src/models.py` + `src/utils/` (foundation)
2. `src/providers/` (data layer, testable independently)
3. `src/portfolio/engine.py` (depends on models + csv_safety)
4. `src/strategies/` (depends on models)
5. `src/guardrails/engine.py` (depends on portfolio + provider health)
6. `src/telegram/` (depends on all above)
7. `scripts/` entry points
8. `config/` + `data/` sample files
9. `.github/workflows/`
10. `tests/`
11. `Makefile` + `requirements.txt`
12. `README.md`

## Verification

- **Unit tests**: `make test` — all 7 test files pass
- **Local dry run**: `make run_weekly_once` with env vars set — generates weekly_plan.json
- **Local alert check**: `make run_alerts_once` — checks prices and prints alerts
- **Local bot test**: `make run_bot_once` — polls once and exits
- **GitHub Actions**: push to repo, verify cron workflows trigger correctly
- **End-to-end**: send `/buy HPG 100 25000` via Telegram → see it in trades.csv → next weekly run picks it up in portfolio
