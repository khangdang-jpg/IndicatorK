# IndicatorK Deployment Guide

Complete step-by-step guide to get your bot running.

## Part A: Create Telegram Bot (Manual - 5 minutes)

### 1. Create Bot on Telegram

Open Telegram and message [@BotFather](https://t.me/BotFather):
```
/newbot
```

Answer the prompts:
- **Bot name**: `IndicatorK Bot`
- **Bot username**: `indicatork_bot` (must be unique, must end with `_bot`)

BotFather responds with:
```
Done! Congratulations on your new bot. You will find it at t.me/indicatork_bot
Use this token to access the HTTP API: 123456789:ABCdefGHIjklmnopQRStuvwxyz
```

**Save your BOT TOKEN**: `123456789:ABCdefGHIjklmnopQRStuvwxyz`

### 2. Get Your Chat ID

Send a message to your new bot at `t.me/indicatork_bot` (any message works).

Then open this URL in your browser, replacing TOKEN with your token from step 1:
```
https://api.telegram.org/bot123456789:ABCdefGHIjklmnopQRStuvwxyz/getUpdates
```

You'll see JSON like:
```json
{
  "ok": true,
  "result": [
    {
      "message": {
        "from": {
          "id": 987654321,
          ...
        }
      }
    }
  ]
}
```

**Save your CHAT ID**: `987654321` (the `id` field under `from`)

---

## Part B: Local Testing (10 minutes)

### 1. Set Environment Variables

```bash
export TELEGRAM_BOT_TOKEN="123456789:ABCdefGHIjklmnopQRStuvwxyz"
export TELEGRAM_ADMIN_CHAT_ID="987654321"
```

Replace with YOUR actual token and chat ID from Part A.

### 2. Run Unit Tests

```bash
cd /Users/khangdang/IndicatorK
make test
```

Expected output:
```
======================== 101 passed in 0.18s ========================
```

### 3. Generate First Weekly Plan

```bash
make run_weekly_once
```

**Check Telegram** - you should receive a message with:
- Weekly trading recommendations
- Portfolio summary
- Guardrails health report

### 4. Test Bot Commands

Send commands to your bot via Telegram:
```
/help
/setcash 10000000
/buy HPG 100 25000
/buy VNM 50 80000
/status
```

### 5. Test Alerts (if during trading hours)

Trading hours: **Mon-Fri 09:00-11:30 and 13:00-15:00 (Asia/Ho_Chi_Minh)**

If it's currently trading hours, run:
```bash
make run_alerts_once
```

If it's outside trading hours, you'll see:
```
Outside Vietnam trading hours — exiting early
```

This is normal. GitHub Actions will run it on schedule.

---

## Part C: Deploy to GitHub (15 minutes)

### 1. Create GitHub Repository

1. Go to [github.com/new](https://github.com/new)
2. **Repository name**: `IndicatorK`
3. **Description**: `Vietnamese personal finance assistant — trading plans + price alerts via Telegram`
4. **Visibility**: **PUBLIC** (so workflows run for free)
5. **Do NOT** initialize with README, .gitignore, or license
6. Click **Create repository**

GitHub will show you commands like:
```
git remote add origin https://github.com/YOUR_USERNAME/IndicatorK.git
git branch -M main
git push -u origin main
```

### 2. Configure Git Locally

```bash
cd /Users/khangdang/IndicatorK

git config --global user.email "your-email@example.com"
git config --global user.name "Your Name"
```

### 3. Initialize Git Repository

```bash
git init
git add .
git commit -m "Initial commit: Vietnamese personal finance assistant MVP

- Zero-cost, zero-LLM design
- Weekly trading plans via configurable strategies
- 5-min price alerts during trading hours
- Telegram bot for manual trade logging
- Config-driven provider & strategy switching
- Guardrails for data quality monitoring
- 101 unit tests, all passing"

git branch -M main
```

### 4. Connect to GitHub

Replace `YOUR_USERNAME` with your GitHub username:

```bash
git remote add origin https://github.com/YOUR_USERNAME/IndicatorK.git
git push -u origin main
```

Enter your GitHub credentials if prompted.

Expected output:
```
Counting objects: 55, done.
Writing objects: 100% (55/55), ...
To https://github.com/YOUR_USERNAME/IndicatorK.git
 * [new branch]      main -> main
Branch 'main' set up to track remote branch 'main' from 'origin'.
```

### 5. Add GitHub Secrets

1. Go to your repo: `https://github.com/YOUR_USERNAME/IndicatorK`
2. Click **Settings** (gear icon, top right)
3. Click **Secrets and variables** → **Actions** (left sidebar)
4. Click **New repository secret**

**Add Secret 1:**
- **Name**: `TELEGRAM_BOT_TOKEN`
- **Value**: Your bot token from Part A (e.g., `123456789:ABCdefGHIjklmnopQRStuvwxyz`)
- Click **Add secret**

**Add Secret 2:**
- **Name**: `TELEGRAM_ADMIN_CHAT_ID`
- **Value**: Your chat ID from Part A (e.g., `987654321`)
- Click **Add secret**

### 6. Test Workflows on GitHub

1. Go to **Actions** tab in your repo
2. Click **Weekly Plan** (left sidebar)
3. Click **Run workflow** button (top right)
4. Click **Run workflow** again in the popup
5. Wait 30 seconds - you'll see a green checkmark when it completes

**Check Telegram** - you should receive another weekly digest message confirming the workflow ran successfully!

### 7. Verify Automatic Schedules

The workflows will now run automatically on these schedules:

| Workflow | Schedule |
|----------|----------|
| **Price Alerts** | Every 5 min, Mon-Fri 9-15 ICT |
| **Weekly Plan** | Sunday 10:00 ICT |
| **Telegram Bot** | Every 5 min, 24/7 |

Go to **Actions** tab and you should see runs appearing as time passes.

---

## Part D: Use Your Bot (Ongoing)

### Send Commands Anytime

Your bot accepts commands 24/7. Open Telegram and send:

```
/help                                    # Show all commands
/setcash 10000000                        # Set cash to 10M
/buy HPG 100 25000                       # Buy 100 HPG at 25,000
/buy VNM 50 80000 fee=500 note=dividend # Buy 50 VNM at 80K, 500 fee
/sell HPG 50 28000                       # Sell 50 HPG at 28,000
/status                                  # View portfolio & PnL
/plan                                    # View current weekly plan
```

### Monitor Weekly Reports

Every Sunday at 10:00 ICT, Telegram sends:
- Top BUY recommendations
- Current portfolio summary
- Allocation vs target
- Guardrails warnings (if any)

### Check Repo Data

Your repo automatically stores:
- `data/trades.csv` - all your trades
- `data/weekly_plan.json` - current plan
- `data/portfolio_weekly.csv` - portfolio value history
- `data/guardrails_report.json` - health metrics

---

## Part E: Customize (No Code Changes!)

### Change Data Source

Edit `config/providers.yml`:
```yaml
primary: http          # or cache
secondary: cache
```

Next workflow run uses the new provider.

### Change Strategy

Edit `config/strategy.yml`:
```yaml
active: rebalance_50_50    # or trend_momentum_atr
```

Next weekly run uses the new strategy.

### Add Symbols

Edit `data/watchlist.txt`:
```
HPG
VNM
FPT
MWG
VCB
```

---

## Troubleshooting

### Bot doesn't respond

Check:
1. Token is correct in GitHub Secrets
2. Chat ID is correct in GitHub Secrets
3. Try sending `/help` again

### No alerts sent

Alerts only run during **Vietnam trading hours** (Mon-Fri 9-15 ICT).
Check if it's currently trading time.

### Workflow failed

Check **Actions** tab → click on failed run → see error details.
Common issues:
- vnstock API timeout (normal, will retry next run)
- Invalid Telegram credentials (check secrets)
- No network (GitHub Actions will retry)

### Tests fail locally

Reinstall dependencies:
```bash
pip3 install -r requirements.txt
make test
```

---

## What Happens Next

1. **5 min**: Bot polls for your commands
2. **Every 5 min (trading hours)**: Price alerts check and send if triggered
3. **Sunday 10:00 ICT**: Weekly plan generated and digest sent
4. **Every week**: Portfolio value snapshot recorded
5. **Ongoing**: Guardrails monitor data quality & performance

---

## Summary

- **Local testing**: ~10 min (once)
- **GitHub setup**: ~15 min (once)
- **Ongoing use**: Just send Telegram commands and check weekly digest

Your bot is now **fully automated** and **costs $0** to run! 🎉

---

For more details, see:
- [README.md](README.md) - Architecture & how it works
- [SETUP.md](SETUP.md) - Detailed technical guide
- [PLAN.md](PLAN.md) - Implementation details
