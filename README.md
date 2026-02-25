# IndicatorK — Vietnamese Personal Finance Assistant

Zero-cost, zero-LLM personal finance MVP for the Vietnamese market. Generates weekly trading plans and sends near-realtime (5-min) price alerts via Telegram, running entirely on GitHub Actions.

## Quick Start

### 1. Create a Telegram Bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the prompts
3. Save the bot token
4. Message your new bot, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your chat ID

### 2. Add GitHub Secrets

Go to **Settings → Secrets and variables → Actions** and add:

| Secret | Value |
|--------|-------|
| `TELEGRAM_BOT_TOKEN` | Your bot token from BotFather |
| `TELEGRAM_ADMIN_CHAT_ID` | Your personal chat ID |

### 3. Enable Workflows

Push the repo to GitHub. Workflows start automatically on schedule.
You can also trigger any workflow manually from the **Actions** tab.

### 4. Local Setup

```bash
pip install -r requirements.txt   # or: make setup
make test                          # run unit tests
```

## How It Works

### Schedules

| Workflow | Schedule | What it does |
|----------|----------|-------------|
| **alerts.yml** | Every 5 min, Mon-Fri during Vietnam trading hours | Fetches prices, checks buy zone / stop loss / take profit alerts, sends Telegram notifications |
| **weekly.yml** | Sunday 10:00 ICT (03:00 UTC) | Generates weekly trading plan, runs guardrails, appends portfolio snapshot, sends digest |
| **bot.yml** | Every 5 min, 24/7 | Polls Telegram for commands (/buy, /sell, /status, etc.) |

### Trading Hours

Vietnam stock market: **Mon-Fri, 09:00-11:30 and 13:00-15:00 (Asia/Ho_Chi_Minh)**. The alerts workflow enforces this strictly — if triggered outside these hours, it exits immediately before making any network calls.

### Telegram Commands

| Command | Description |
|---------|-------------|
| `/buy SYMBOL QTY PRICE [asset=stock\|bond\|fund] [fee=N] [note=TEXT]` | Record a buy trade |
| `/sell SYMBOL QTY PRICE [asset=stock\|bond\|fund] [fee=N] [note=TEXT]` | Record a sell trade |
| `/setcash AMOUNT` | Set cash balance |
| `/status` | View portfolio positions & allocation |
| `/plan` | View current weekly plan |
| `/help` | Show command reference |

Only messages from `TELEGRAM_ADMIN_CHAT_ID` are processed.

## When Files Are Committed (and Why)

This project is designed for a **public GitHub repo** and minimizes commits to prevent repo bloat:

| File | When committed | Why |
|------|---------------|-----|
| `data/alerts_state.json` | Only when alert state actually changes (new alert fired or zone entry/exit) | Dedup requires persistent state |
| `data/bot_state.json` | Only when new Telegram updates are processed | Prevents double-processing messages |
| `data/trades.csv` | Only when a /buy, /sell, or /setcash command is processed | Trade log is append-only |
| `data/weekly_plan.json` | Once per week (weekly workflow) | New plan each week |
| `data/guardrails_report.json` | Once per week (weekly workflow) | Health check report |
| `data/portfolio_weekly.csv` | Once per week (weekly workflow) | Portfolio value history for metrics |
| `data/prices_cache.json` | Once per week (weekly workflow only) | **NOT** committed on 5-min runs — only as weekly backup |

**If there is no diff, no commit is created.** All workflows use `git diff --staged --quiet` to skip empty commits.

## How to Change Data Source

Edit `config/providers.yml`:

```yaml
primary: vnstock       # Options: vnstock | http | cache
secondary: http        # Fallback if primary fails
```

No code changes required. The system uses a **composite provider** that tries primary → secondary → cache automatically.

**Available providers:**
- `vnstock` — vnstock library (guest mode, no API key, purpose-built for Vietnamese stocks)
- `http` — Simplize public API (no auth)
- `cache` — Read from `data/prices_cache.json` (offline fallback)

## How to Change Strategy

Edit `config/strategy.yml`:

```yaml
active: trend_momentum_atr   # Options: trend_momentum_atr | rebalance_50_50
```

**Available strategies:**
- `trend_momentum_atr` — Weekly trend (MA10w/MA30w), momentum (RSI), ATR-based buy zones and stops
- `rebalance_50_50` — Allocation-first: maintain 50/50 stock vs bond+fund, rebalance on drift > 5%

Each strategy has configurable parameters in the same YAML file.

## How Guardrails Work

The guardrails engine runs during the weekly workflow and produces `data/guardrails_report.json`:

**Data quality checks:**
- Provider error rate > 30% → recommends `SWITCH_PROVIDER`
- Missing price rate > 50% → recommends `SWITCH_PROVIDER`

**Performance checks** (from `data/portfolio_weekly.csv` snapshots):
- Rolling 12-week return below 50% of benchmark (9%/year) → recommends `SWITCH_STRATEGY`
- Max drawdown > 15% → recommends `DE_RISK`

**To apply a recommendation:**
1. Read `data/guardrails_report.json` → check `recommendations`
2. If `SWITCH_PROVIDER`: edit `config/providers.yml` to change `primary`
3. If `SWITCH_STRATEGY`: edit `config/strategy.yml` to change `active`
4. If `DE_RISK`: edit `config/risk.yml` to lower position limits

Guardrail warnings are included in the weekly Telegram digest automatically.

## How to Add Symbols to Watchlist

Edit `data/watchlist.txt` — one symbol per line:

```
HPG
VNM
FPT
MWG
VCB
```

Lines starting with `#` are comments. If the file is empty, a built-in default list is used.

## Keeping the Repo Healthy

- **Cache is not bloated**: `prices_cache.json` is only committed once per week
- **No empty commits**: all workflows check for diffs before committing
- **Concurrency controls**: workflows use `concurrency` groups to prevent git conflicts
- **[skip ci]** tags on alert/bot commits prevent recursive workflow triggers

## Architecture

```
src/
├── models.py              # Shared dataclasses
├── providers/             # Data source layer (swappable via config)
│   ├── base.py            # PriceProvider interface
│   ├── vnstock_provider   # vnstock library
│   ├── http_provider      # Simplize API
│   ├── cache_provider     # JSON file cache
│   └── composite_provider # Fallback chain
├── strategies/            # Strategy layer (swappable via config)
│   ├── base.py            # Strategy interface
│   ├── trend_momentum_atr # MA + RSI + ATR
│   └── rebalance_50_50   # 50/50 allocation
├── guardrails/            # Health monitoring
├── portfolio/             # Trades → positions → PnL → allocation
├── telegram/              # Bot, commands, alerts, formatting
└── utils/                 # Config, trading hours, CSV safety, logging
```

## Running Locally

```bash
# Set environment variables
export TELEGRAM_BOT_TOKEN="your-token"
export TELEGRAM_ADMIN_CHAT_ID="your-chat-id"

# Run each workflow component
make run_weekly_once     # Generate weekly plan
make run_alerts_once     # Check price alerts (requires trading hours)
make run_bot_once        # Poll for Telegram commands
make test                # Run all unit tests
```

## Risk Disclaimer

This is a **personal tracking and alerting tool**, not investment advice. All strategies are mechanical and rule-based. Always do your own research before making investment decisions. The data providers may return incomplete or inaccurate data — see the guardrails system for monitoring data quality.
