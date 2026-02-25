# IndicatorK — Vietnamese Personal Finance Assistant

Zero-cost, zero-LLM personal finance MVP for the Vietnamese market. Generates weekly trading plans and sends near-realtime (5-min) price alerts via Telegram, running entirely on GitHub Actions.

**Status**: ✅ Production ready | 101 tests passing | Fully documented

---

## 🚀 Quick Start

### 1. Entry Point
Start here: **[00_START_HERE_FIRST.txt](00_START_HERE_FIRST.txt)** (5 minutes)

### 2. Deploy to GitHub
Choose one:
- **Fastest** (15 min): Run `./GITHUB_DEPLOY.sh`
- **Guided** (20 min): Read [docs/01_DEPLOYMENT_GUIDE.md](docs/01_DEPLOYMENT_GUIDE.md)
- **Learning** (25 min): Read [docs/00_README.md](docs/00_README.md) first

### 3. Add GitHub Secrets
After creating your repo on GitHub:
1. Go to **Settings → Secrets and variables → Actions**
2. Add `TELEGRAM_BOT_TOKEN`: `8620394249:AAEe209BkfQ_VaCBkhq6Xq0X34AWFxSX4LQ`
3. Add `TELEGRAM_ADMIN_CHAT_ID`: `6226624607`

### 4. Test Workflows
1. Go to **Actions** tab
2. Click **Weekly Plan** → **Run workflow**
3. Check Telegram for the weekly digest ✅

---

## 📚 Documentation

All guides are in the `docs/` folder (consolidated and deduplicated):

| Guide | Purpose | Read Time |
|-------|---------|-----------|
| [docs/00_README.md](docs/00_README.md) | Main overview | 10 min |
| [docs/01_DEPLOYMENT_GUIDE.md](docs/01_DEPLOYMENT_GUIDE.md) | **Full deployment** | 15 min ⭐ |
| [docs/02_TECHNICAL_SETUP.md](docs/02_TECHNICAL_SETUP.md) | Technical details & troubleshooting | 15 min |
| [docs/03_ARCHITECTURE.md](docs/03_ARCHITECTURE.md) | What was built & architecture | 10 min |
| [docs/04_IMPLEMENTATION_PLAN.md](docs/04_IMPLEMENTATION_PLAN.md) | 12-phase implementation | 20 min |
| [docs/05_PROJECT_STATUS.txt](docs/05_PROJECT_STATUS.txt) | Detailed status report | 5 min |
| [docs/06_DOCUMENTATION_INDEX.md](docs/06_DOCUMENTATION_INDEX.md) | Full documentation index | 5 min |
| [docs/07_COMMANDS_REFERENCE.txt](docs/07_COMMANDS_REFERENCE.txt) | Telegram commands cheat sheet | 2 min |
| [docs/08_TELEGRAM_BOT_SETUP.txt](docs/08_TELEGRAM_BOT_SETUP.txt) | How to create Telegram bot | 10 min |
| [docs/09_DEPLOYMENT_CHECKLIST.txt](docs/09_DEPLOYMENT_CHECKLIST.txt) | Deployment checklist | 5 min |

---

## ✨ What You Get

### 🤖 Telegram Bot (24/7)
```
/buy HPG 100 25000          Record a buy trade
/sell HPG 50 28000          Record a sell trade
/setcash 10000000           Set cash balance
/status                     View portfolio
/plan                       View current plan
/help                       Show commands
```

### 📊 Weekly Trading Plans (Sunday 10 AM ICT)
- Two strategies: `trend_momentum_atr` or `rebalance_50_50`
- Automatic guardrails monitoring
- Portfolio snapshot recording

### 📢 Price Alerts (Every 5 min, trading hours only)
- Smart deduplication (no spam)
- Buy zones, take profit, stop loss levels
- 24-hour re-alert window

### 💾 Portfolio Tracking
- FIFO position tracking
- Realized/unrealized PnL
- Allocation monitoring
- Multi-provider support (vnstock → HTTP → cache)

---

## 💰 Cost

| Component | Cost |
|-----------|------|
| GitHub Actions | $0 (free for public repos) |
| vnstock API | $0 (guest mode, no key) |
| Simplize HTTP API | $0 (free public endpoint) |
| Telegram Bot | $0 |
| LLM calls | $0 (none - pure logic) |
| **Total** | **$0/month forever** |

---

## 🏗️ Architecture

```
src/
├── models.py              # Shared dataclasses
├── providers/             # Data layer (swappable)
│   ├── base.py
│   ├── vnstock_provider
│   ├── http_provider
│   ├── cache_provider
│   └── composite_provider
├── strategies/            # Trading logic (swappable)
│   ├── base.py
│   ├── trend_momentum_atr
│   └── rebalance_50_50
├── guardrails/            # Health monitoring
├── portfolio/             # Position tracking
├── telegram/              # Bot & commands
└── utils/                 # Config, logging, validation
```

---

## ⚙️ Customize (No Code Changes Needed)

### Change Data Source
Edit `config/providers.yml`:
```yaml
primary: http              # vnstock | http | cache
```

### Change Strategy
Edit `config/strategy.yml`:
```yaml
active: rebalance_50_50    # trend_momentum_atr | rebalance_50_50
```

### Add Stocks to Watchlist
Edit `data/watchlist.txt`:
```
HPG
VNM
FPT
MWG
```

### Adjust Risk Parameters
Edit `config/risk.yml` (max drawdown, benchmark CAGR, etc.)

---

## 🧪 Testing

```bash
# Run all 101 tests
make test

# Run specific test
pytest tests/test_portfolio.py -v

# Local Telegram setup
export TELEGRAM_BOT_TOKEN="your-token"
export TELEGRAM_ADMIN_CHAT_ID="your-chat-id"
make run_weekly_once
```

---

## 🔄 Workflows

| Workflow | Schedule | Action |
|----------|----------|--------|
| **alerts.yml** | Every 5 min (trading hours) | Check prices → send alerts |
| **weekly.yml** | Sunday 10:00 AM ICT | Generate plan → send digest |
| **bot.yml** | Every 5 min (24/7) | Poll Telegram → log trades |

---

## 📋 Quick Links

- **Start here**: [00_START_HERE_FIRST.txt](00_START_HERE_FIRST.txt)
- **Deploy guide**: [docs/01_DEPLOYMENT_GUIDE.md](docs/01_DEPLOYMENT_GUIDE.md)
- **Commands**: [docs/07_COMMANDS_REFERENCE.txt](docs/07_COMMANDS_REFERENCE.txt)
- **Troubleshooting**: [docs/02_TECHNICAL_SETUP.md](docs/02_TECHNICAL_SETUP.md)
- **Architecture**: [docs/03_ARCHITECTURE.md](docs/03_ARCHITECTURE.md)

---

## 📊 Local Testing Results

✅ **Telegram**: Verified working
✅ **Tests**: 101/101 passing
✅ **Weekly plan**: Generating successfully
✅ **Alerts**: Dedup working
✅ **Portfolio**: FIFO tracking working

---

## ⚠️ Risk Disclaimer

This is a **personal tracking and alerting tool**, not investment advice. All strategies are mechanical and rule-based. Always do your own research before making investment decisions.

---

## 🎯 Next Step

**Choose one:**

1. **Deploy now**: `./GITHUB_DEPLOY.sh`
2. **Read guide**: [docs/01_DEPLOYMENT_GUIDE.md](docs/01_DEPLOYMENT_GUIDE.md)
3. **Learn first**: [00_START_HERE_FIRST.txt](00_START_HERE_FIRST.txt)

---

**Ready?** → Start with [00_START_HERE_FIRST.txt](00_START_HERE_FIRST.txt) 🚀
