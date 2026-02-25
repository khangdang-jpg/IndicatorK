# 🚀 START HERE - IndicatorK Bot Deployment

**Welcome!** This guide will take you from zero to a fully-functional trading bot in **~30 minutes**.

---

## What You're Getting

A **zero-cost** personal finance bot that:
- ✅ Tracks your stock portfolio (buy/sell via Telegram)
- ✅ Generates weekly trading plans on Sundays
- ✅ Sends price alerts every 5 minutes during trading
- ✅ Runs entirely on GitHub Actions (free forever)
- ✅ No LLM calls (no token costs)

---

## 5-Step Quick Start

### Step 1️⃣: Create Telegram Bot (5 min)

1. Open Telegram → message `@BotFather`
2. Send: `/newbot`
3. Enter name: `IndicatorK Bot`
4. Enter username: `indicatork_bot` (must be unique)
5. **SAVE** the token BotFather gives you

Then get your chat ID:
1. Message your new bot
2. Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. Find and **SAVE** the `id` field (from.id)

**You now have:**
- `TELEGRAM_BOT_TOKEN` = the long token
- `TELEGRAM_ADMIN_CHAT_ID` = your chat ID number

---

### Step 2️⃣: Test Locally (10 min)

Set your credentials:
```bash
export TELEGRAM_BOT_TOKEN="your_token_here"
export TELEGRAM_ADMIN_CHAT_ID="your_chat_id_here"
```

Run the test suite:
```bash
cd /Users/khangdang/IndicatorK
make test
```
Should show: ✅ **101 passed**

Test the bot:
```bash
make run_weekly_once
```
Check Telegram → should receive a message with trading plan!

---

### Step 3️⃣: Deploy to GitHub (10 min)

Create a new repo at [github.com/new](https://github.com/new):
- Name: `IndicatorK`
- **PUBLIC**
- Don't add README

Then run (replace YOUR_USERNAME):
```bash
cd /Users/khangdang/IndicatorK

git config --global user.email "your-email@gmail.com"
git config --global user.name "Your Name"

git init
git add .
git commit -m "Initial commit: Vietnamese personal finance assistant MVP"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/IndicatorK.git
git push -u origin main
```

---

### Step 4️⃣: Add GitHub Secrets (5 min)

1. Go to your GitHub repo
2. **Settings** → **Secrets and variables** → **Actions**
3. Add two new secrets:
   - Name: `TELEGRAM_BOT_TOKEN` | Value: your token
   - Name: `TELEGRAM_ADMIN_CHAT_ID` | Value: your chat ID

---

### Step 5️⃣: Verify It Works (5 min)

1. Go to **Actions** tab
2. Click **Weekly Plan**
3. Click **Run workflow**
4. Wait 30 seconds → should see ✅ green checkmark
5. Check Telegram → should receive a message!

**That's it! 🎉 Your bot is live!**

---

## Now What?

### Daily Use
Send Telegram commands anytime:
```
/buy HPG 100 25000          # Record a buy
/status                      # Check portfolio
/help                        # See all commands
```

### Weekly
Every Sunday at 10:00 AM Vietnam time, you get:
- Top buying opportunities
- Current portfolio analysis
- Guardrails warnings (if any)

### Automated
The bot runs completely automatically:
- **Every 5 min (trading hours)**: Price alerts
- **Every 5 min (24/7)**: Command polling
- **Every Sunday 10 AM**: Weekly plan generation

---

## Customization (Optional)

**No code changes needed!** Just edit config files:

**Change strategy:**
Edit `config/strategy.yml`:
```yaml
active: rebalance_50_50    # Instead of trend_momentum_atr
```

**Change data source:**
Edit `config/providers.yml`:
```yaml
primary: http              # Instead of vnstock
```

**Add more symbols:**
Edit `data/watchlist.txt`:
```
HPG
VNM
FPT
MWG
```

---

## Detailed Guides

- 📖 [DEPLOY.md](DEPLOY.md) - Full step-by-step guide
- 📖 [README.md](README.md) - Architecture & features
- 📖 [CHECKLIST.txt](CHECKLIST.txt) - Printable checklist
- 📖 [PLAN.md](PLAN.md) - Implementation details

---

## Troubleshooting

**Tests fail?**
```bash
pip3 install -r requirements.txt
make test
```

**Bot doesn't respond?**
- Check GitHub Secrets are correct
- Try sending `/help`

**Alerts not working?**
- Alerts only run Mon-Fri 9-15 (Vietnam time)
- Check it's trading hours

---

## Files & What They Do

```
/src                    → Core application logic
/config                 → Strategy, provider, risk settings (edit these!)
/data                   → Portfolio data (trades, snapshots, cache)
/.github/workflows      → Automated tasks (run on schedule)
/tests                  → 101 unit tests (all passing)
```

---

## Key Features

✅ **Zero Cost** - GitHub Actions + free APIs + no LLM calls  
✅ **Config-Driven** - Change strategy/provider without code  
✅ **Modular** - Pluggable providers & strategies  
✅ **Safe** - CSV injection prevention, symbol validation  
✅ **Monitored** - Guardrails track data quality & performance  
✅ **Tested** - 101 unit tests, all passing  

---

## Support & Questions

1. Check the relevant `.md` file above
2. Review the checklist if something fails
3. All code is in `/src` with clear module separation

---

**Ready? Follow the 5 steps above!** ⬆️

Questions? Start with [DEPLOY.md](DEPLOY.md) for the detailed version.
