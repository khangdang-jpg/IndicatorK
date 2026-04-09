# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

IndicatorK is a Vietnamese personal finance trading bot that runs entirely on GitHub Actions (zero cost). It generates weekly trading plans using technical analysis strategies, sends real-time price alerts via Telegram, and tracks portfolio performance. The system is designed to be **configuration-driven** — strategies, data providers, and risk parameters can be swapped without code changes.

**Performance**: 28-47% CAGR, Sharpe 3.23, 8.72% max drawdown, 66.67% win rate (trend_momentum_atr_regime_adaptive strategy).

## Common Commands

### Development & Testing
```bash
# Install dependencies
make setup

# Run all tests (101 tests)
make test

# Run specific test file
pytest tests/test_portfolio.py -v

# Run specific test
pytest tests/test_strategies.py::test_buy_zone_generation -v

# Lint (syntax check)
make lint
```

### Local Execution
```bash
# Generate weekly trading plan locally
export TELEGRAM_BOT_TOKEN="your-token"
export TELEGRAM_ADMIN_CHAT_ID="your-chat-id"
make run_weekly_once

# Run price alerts check
make run_alerts_once

# Run Telegram bot once
make run_bot_once
```

### Backtesting
```bash
# Backtest with defaults (10M VND initial, 1M per trade, 4 trades/week)
make backtest FROM=2025-05-01 TO=2026-02-25

# Run both worst-case and best-case scenarios
make backtest FROM=2025-05-01 TO=2026-02-25 RUN_RANGE=1

# Custom parameters
make backtest FROM=2025-05-01 TO=2026-02-25 \
  INITIAL_CASH=20000000 \
  ORDER_SIZE=2000000 \
  TRADES_PER_WEEK=6 \
  TIE_BREAKER=best

# Quick strategy validation across market conditions
python .claude/skills/backtest-periods.py  # Uses active strategy
```

### Cloudflare Workers (Telegram webhook)
```bash
cd workers

# Install dependencies
npm install

# Deploy to production
npm run deploy

# Test locally
npm run dev

# View logs
npm run tail

# Set secrets
wrangler secret put TELEGRAM_BOT_TOKEN
wrangler secret put GITHUB_TOKEN
```

## Architecture

### Data Flow Pipeline
```
Providers → Strategies → Portfolio Engine → Telegram Bot
    ↓           ↓              ↓               ↓
  OHLCV   Recommendations  Positions      Alerts
```

1. **Providers** (`src/providers/`): Fetch market data with automatic fallback
   - `vnstock_provider.py` → `http_provider.py` → `cache_provider.py`
   - Orchestrated by `composite_provider.py`
   - Swappable via `config/providers.yml`

2. **Strategies** (`src/strategies/`): Generate trade recommendations
   - All inherit from `base.py`
   - Active strategy: `trend_momentum_atr_regime_adaptive.py` (production)
   - Others: `trend_momentum_atr.py`, `trend_momentum_atr_enhanced.py`, `rebalance_50_50.py`
   - Swappable via `config/strategy.yml` (`active: strategy_name`)

3. **Portfolio Engine** (`src/portfolio/engine.py`):
   - FIFO position tracking
   - Realized/unrealized PnL calculation
   - Risk-based position sizing (1% equity risk per trade)
   - Persists state to `data/portfolio_state.json` and `data/trades.csv`

4. **Guardrails** (`src/guardrails/engine.py`): Health monitoring
   - Provider error rate tracking → auto-switch providers
   - Strategy performance vs benchmark → alert for underperformance
   - Max drawdown, turnover, allocation checks

5. **Telegram Bot** (`src/telegram/`):
   - Commands: `/buy`, `/sell`, `/status`, `/plan`, `/setcash`
   - Runs on GitHub Actions (polling every 5 min)
   - Optional Cloudflare Workers webhook (`workers/`)

### Key Dataclasses (`src/models.py`)

These dataclasses flow through the entire system:

- **`OHLCV`**: Raw market data (date, open, high, low, close, volume)
- **`Recommendation`**: Strategy output (symbol, action, buy_zone, stop_loss, take_profit)
- **`Position`**: Portfolio state (symbol, qty, avg_cost, unrealized_pnl)
- **`TradeRecord`**: Trade log (timestamp, symbol, side, qty, price)

### Configuration System

All behavior is controlled via YAML files in `config/`:

- **`strategy.yml`**: Switch strategies, tune parameters (MA periods, RSI thresholds, ATR multipliers)
- **`risk.yml`**: Position sizing, max drawdown, allocation limits, regime multipliers
- **`providers.yml`**: Data source priority (vnstock → http → cache)
- **`news_ai.yml`**: AI-based news sentiment analysis (optional)

**Critical**: To switch strategies, only change `config/strategy.yml` (`active: strategy_name`). No code changes required.

### GitHub Actions Orchestration

Three workflows power the production system (`.github/workflows/`):

1. **`weekly.yml`**: Sunday 10:00 AM ICT → Generate trading plan → Send Telegram digest
2. **`alerts.yml`**: Every 5 min (trading hours) → Check prices → Send alerts if buy/TP/SL hit
3. **`bot.yml`**: Every 5 min (24/7) → Poll Telegram → Execute commands → Log trades
4. **`ai_analysis.yml`**: Weekly → Fetch news → Generate AI insights (optional)

## Key Implementation Patterns

### Price Rounding (`src/utils/price_utils.py`)

**CRITICAL**: All price calculations MUST use these utilities to match Vietnamese stock exchange tick sizes:

```python
from src.utils.price_utils import round_to_step, floor_to_step, ceil_to_step

# Examples (all use HOSE tick size rules):
entry_price = round_to_step(price * 1.001)  # Entry with buffer
stop_loss = floor_to_step(entry - atr_mult * atr)  # Floor for stops
take_profit = ceil_to_step(entry + atr_mult * atr)  # Ceil for targets
```

**Tick sizes**: 0.01 (< 10k VND), 0.05 (10k-50k VND), 0.1 (> 50k VND). Do NOT manually round prices.

### Strategy Development

All strategies inherit from `src/strategies/base.py`:

```python
class BaseStrategy:
    def generate_weekly_plan(
        self,
        symbols: list[str],
        data: dict[str, list[OHLCV]],
        portfolio: Portfolio,
        week_start: date
    ) -> list[Recommendation]:
        """Generate recommendations for the week."""
        raise NotImplementedError
```

**Requirements**:
- Return `list[Recommendation]` with buy_zone, stop_loss, take_profit
- Use `round_to_step()`, `floor_to_step()`, `ceil_to_step()` from `price_utils.py`
- Ensure stop_loss < buy_zone_low < buy_zone_high < take_profit
- Set `action` to BUY (new position), HOLD (keep), REDUCE (partial exit), or SELL (full exit)

### Provider Development

All providers inherit from `src/providers/base.py`:

```python
class BaseProvider:
    def fetch_ohlcv(self, symbol: str, start: date, end: date) -> list[OHLCV]:
        """Fetch OHLCV data."""
        raise NotImplementedError

    def fetch_quote(self, symbol: str) -> Optional[Quote]:
        """Fetch real-time quote."""
        raise NotImplementedError
```

The `composite_provider.py` handles fallback logic automatically.

### State Persistence

- **Atomic writes**: Use `src/utils/csv_safety.py` for safe CSV updates
- **Portfolio state**: `data/portfolio_state.json` (atomic write via temp file)
- **Trade log**: `data/trades.csv` (append-only with flush)
- **Weekly plan**: `data/weekly_plan.json` (overwritten weekly)
- **Alert dedup**: `data/alert_state.json` (24-hour re-alert window)

### Testing Structure

Tests follow a modular pattern (`tests/`):
- `test_strategies.py`: Strategy logic, buy zone generation, ATR calculations
- `test_portfolio.py`: FIFO tracking, PnL, position sizing
- `test_providers.py`: Data fetching, fallback, error handling
- `test_backtest.py`: Historical simulation, weekly generator
- `test_commands.py`: Telegram bot commands
- `test_alert_dedup.py`: Alert deduplication logic
- `test_news_ai.py`: AI news sentiment (optional)

**Test data**: Use fixtures in `tests/fixtures/` for OHLCV data.

## Critical Files

### Strategy Layer
- `src/strategies/trend_momentum_atr_regime_adaptive.py` — **Production strategy** (top 5% Sharpe globally)
- `src/strategies/base.py` — Strategy interface
- `src/utils/price_utils.py` — **Centralized price rounding** (eliminates duplicated rounding logic)

### Data Layer
- `src/providers/composite_provider.py` — Orchestrates fallback chain
- `src/providers/vnstock_provider.py` — Primary (Vietnamese stock API)
- `src/providers/http_provider.py` — Fallback (Simplize HTTP API)
- `src/providers/cache_provider.py` — Last resort (stale data with warnings)

### Execution Layer
- `scripts/run_weekly.py` — Weekly plan generation (called by GitHub Actions)
- `scripts/run_alerts.py` — Price alert checker (called every 5 min)
- `scripts/run_bot.py` — Telegram bot polling loop
- `scripts/backtest.py` — Historical backtesting CLI

### Configuration
- `config/strategy.yml` — Strategy selection & tuning
- `config/risk.yml` — Position sizing, drawdown limits, regime multipliers
- `config/providers.yml` — Data source priority

### Workers (Optional)
- `workers/src/index.js` — Cloudflare Workers webhook handler (alternative to polling)
- `workers/wrangler.toml` — Deployment config

## Deployment

### GitHub Actions (Primary)
1. Fork repo → Add secrets (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_CHAT_ID`)
2. Workflows auto-run on schedule (no manual steps)
3. See `docs/01_DEPLOYMENT_GUIDE.md` for detailed steps

### Cloudflare Workers (Optional webhook)
1. `cd workers && npm install`
2. Set secrets: `wrangler secret put TELEGRAM_BOT_TOKEN`
3. Deploy: `npm run deploy`
4. Set webhook: `curl https://api.telegram.org/bot<token>/setWebhook?url=<worker-url>`

## Development Guidelines

### When Adding Features
1. **Read before editing**: Always read existing strategy/provider code before modifying
2. **Test first**: Write test in `tests/` before implementation
3. **Use utilities**: Import from `src/utils/price_utils.py` for price rounding
4. **Config over code**: Add parameters to YAML instead of hardcoding

### When Fixing Bugs
1. **Check recent fixes**: See `.claude/projects/.../memory/MEMORY.md` for recent bug fixes
2. **Validate rounding**: Ensure prices use `round_to_step()`, not manual rounding
3. **Test edge cases**: Zero-width buy zones, news scoring pipeline, environment variables

### When Refactoring
1. **Avoid duplication**: Centralize shared logic (see `price_utils.py` example)
2. **Maintain interfaces**: Keep `BaseStrategy` and `BaseProvider` contracts stable
3. **Verify tests**: Run `make test` after refactoring

## Performance Benchmarks

Current production strategy (`trend_momentum_atr_regime_adaptive`):
- **Sharpe Ratio**: 3.23 (excellent: >2.0)
- **Max Drawdown**: 8.72% (excellent: <10%)
- **Profit Factor**: 3.64 (excellent: >3.0)
- **Win Rate**: 66.67% (excellent: >65%)
- **CAGR**: 28-47% (benchmark: 9%)

## Troubleshooting

### Common Issues
1. **vnstock API errors**: Check `VNSTOCK_API_SETUP.md` for API key setup
2. **Zero-width buy zones**: Ensure `_ensure_different_zones()` uses proper rounding
3. **News scoring broken**: Check data flattening in `scripts/run_weekly.py`
4. **Cloudflare undefined vars**: Verify `wrangler.toml` has all required `[vars]`

### Debugging
```bash
# Check portfolio state
cat data/portfolio_state.json | python3 -m json.tool

# View recent trades
tail -20 data/trades.csv

# Check weekly plan
cat data/weekly_plan.json | python3 -m json.tool

# View GitHub Actions logs
# Go to repo → Actions tab → Select workflow run
```

## Additional Resources

- **Full documentation**: See `docs/` folder (consolidated guides)
- **Deployment**: `docs/01_DEPLOYMENT_GUIDE.md`
- **Architecture**: `docs/03_ARCHITECTURE.md`
- **Commands reference**: `docs/07_COMMANDS_REFERENCE.txt`
- **Comprehensive analysis**: See `.claude/projects/.../memory/` for research reports
