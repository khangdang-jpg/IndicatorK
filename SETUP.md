# IndicatorK Setup Guide

Complete setup from testing to deployment.

## Phase 1: Create Telegram Bot

### Step 1.1: Open Telegram BotFather

Open Telegram and message [@BotFather](https://t.me/BotFather)

### Step 1.2: Create New Bot

Send this message to BotFather:
```
/newbot
```

BotFather will ask for:
- **Bot name** (e.g., "IndicatorK Bot")
- **Bot username** (e.g., "indicatork_bot" — must end with `_bot` and be unique)

### Step 1.3: Save Your Bot Token

BotFather will respond with:
```
Done! Congratulations on your new bot. You will find it at t.me/YOUR_BOT_USERNAME
Use this token to access the HTTP API: 123456789:ABCdefGHIjklmnopQRStuvwxyz
```

**Copy and save the token** (everything after "Use this token to access"):
```
YOUR_BOT_TOKEN = 123456789:ABCdefGHIjklmnopQRStuvwxyz
```

### Step 1.4: Get Your Chat ID

1. Message your new bot (find it at `t.me/YOUR_BOT_USERNAME`) and send any message (e.g., `/start`)

2. Open this URL in your browser (replace with your token):
```
https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates
```

You'll see JSON like:
```json
{
  "ok": true,
  "result": [
    {
      "update_id": 123456789,
      "message": {
        "message_id": 1,
        "from": {
          "id": YOUR_CHAT_ID,
          "is_bot": false,
          "first_name": "Your Name"
        },
        ...
      }
    }
  ]
}
```

**Copy your chat ID** (the `id` under `from`):
```
YOUR_ADMIN_CHAT_ID = YOUR_CHAT_ID
```

---

## Phase 2: Test Locally

### Step 2.1: Set Environment Variables

```bash
export TELEGRAM_BOT_TOKEN="YOUR_BOT_TOKEN"
export TELEGRAM_ADMIN_CHAT_ID="YOUR_ADMIN_CHAT_ID"
```

Example:
```bash
export TELEGRAM_BOT_TOKEN="123456789:ABCdefGHIjklmnopQRStuvwxyz"
export TELEGRAM_ADMIN_CHAT_ID="987654321"
```

### Step 2.2: Run Unit Tests

```bash
make test
```

Expected output:
```
======================== 101 passed in 0.18s ========================
```

### Step 2.3: Generate First Weekly Plan

```bash
make run_weekly_once
```

This will:
- Fetch 52 weeks of history for watchlist symbols
- Generate weekly trading plan
- Calculate guardrails report
- Create portfolio snapshot
- Send Telegram digest

**Check Telegram** — you should receive a weekly digest message.

### Step 2.4: Test Bot Commands (24/7)

```bash
make run_bot_once
```

Then send commands to your bot via Telegram:
```
/buy HPG 100 25000
/status
/help
```

**Check the terminal** — you should see logs like:
```
2025-01-XX 10:30:45 [INFO] telegram.bot: Processed 1 update
```

**Check trades.csv** — the buy command should be logged:
```bash
cat data/trades.csv
```

### Step 2.5: Test Alerts (Trading Hours Only)

Alerts only work Mon-Fri 09:00-11:30 and 13:00-15:00 (Asia/Ho_Chi_Minh).

During trading hours, run:
```bash
make run_alerts_once
```

You should see logs like:
```
2025-01-XX 10:30:45 [INFO] composite: vnstock returned 10/10 prices
2025-01-XX 10:30:46 [INFO] Alerts check complete: 0 alerts sent
```

Or if an alert is triggered:
```
2025-01-XX 10:30:46 [INFO] Alert sent: BUY ZONE HPG: 25000 (zone 24000-25500)
```

---

## Phase 3: Deploy to GitHub

### Step 3.1: Create GitHub Repository

1. Go to [github.com/new](https://github.com/new)
2. Repository name: `IndicatorK`
3. Description: `Vietnamese personal finance assistant — trading plans + price alerts via Telegram`
4. Public (so workflows run for free)
5. **Do NOT initialize** with README, .gitignore, or license
6. Click **Create repository**

### Step 3.2: Initialize Git & Push

```bash
cd /Users/khangdang/IndicatorK

git config --global user.email "YOUR_EMAIL@example.com"
git config --global user.name "Your Name"

git init
git add .
git commit -m "Initial commit: Vietnamese personal finance assistant MVP

- Zero-cost, zero-LLM design
- Weekly trading plans via trend_momentum_atr or rebalance_50_50 strategies
- 5-min price alerts (trading hours only)
- Telegram bot for manual trade logging
- Config-driven provider & strategy switching
- Guardrails for data quality & performance monitoring
- 101 unit tests, all passing"

git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/IndicatorK.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your GitHub username and `YOUR_EMAIL` with your email.

### Step 3.3: Add GitHub Secrets

1. Go to your repo on GitHub
2. **Settings → Secrets and variables → Actions**
3. Click **New repository secret**

Add two secrets:

**Secret 1:**
- Name: `TELEGRAM_BOT_TOKEN`
- Value: `123456789:ABCdefGHIjklmnopQRStuvwxyz` (your bot token)

**Secret 2:**
- Name: `TELEGRAM_ADMIN_CHAT_ID`
- Value: `987654321` (your chat ID)

Click **Add secret** for each.

### Step 3.4: Enable Workflows (If Needed)

1. Go to **Actions** tab in your repo
2. If workflows show "disabled", click **Enable**
3. You should see 3 workflows:
   - **Price Alerts** (every 5 min, Mon-Fri trading hours)
   - **Weekly Plan** (Sunday 10:00 ICT)
   - **Telegram Bot** (every 5 min, 24/7)

### Step 3.5: Trigger Workflows Manually

1. Go to **Actions** tab
2. Click **Weekly Plan**
3. Click **Run workflow** button
4. Wait ~30 seconds for it to complete
5. Check Telegram — you should receive the weekly digest

---

## Phase 4: Verify Deployment

### Check 1: Workflows are running

Go to **Actions** tab → see green checkmarks on recent runs.

### Check 2: Telegram messages

Send a test command to your bot:
```
/status
```

You should get a response showing portfolio (empty at start).

### Check 3: Repo has weekly data

Go to **data/ folder** in repo — you should see:
- `weekly_plan.json` — latest plan
- `guardrails_report.json` — health report
- `portfolio_weekly.csv` — snapshot (1 row so far)
- `prices_cache.json` — cached prices

### Check 4: Trading command via Telegram

Send:
```
/buy HPG 100 25000
```

Check that bot responds with confirmation, then go to your repo:
- **data/trades.csv** should have 1 new row

---

## Phase 5: Customization

### Change Data Source (No Code Changes!)

Edit `config/providers.yml`:

```yaml
# Use HTTP provider instead of vnstock
primary: http
secondary: cache
```

Next workflow run will automatically use HTTP.

### Change Strategy (No Code Changes!)

Edit `config/strategy.yml`:

```yaml
# Switch to rebalance_50_50 strategy
active: rebalance_50_50
rebalance_50_50:
  stock_target: 0.50
  bond_fund_target: 0.50
  drift_threshold: 0.05
```

Next weekly run will generate plans using the new strategy.

### Add Symbols to Watchlist

Edit `data/watchlist.txt`:

```
HPG
VNM
FPT
MWG
VCB
TCB
MBB
ACBS
VJC
VGC
```

---

## Troubleshooting

### "Workflow doesn't have permission to push"

GitHub Actions needs write access. In **Settings → Actions → General**:
- Workflow permissions: **Read and write permissions** (selected)
- Allow GitHub Actions to create and approve PRs: checked

### "Telegram bot not responding"

1. Verify bot token is correct in GitHub Secrets
2. Verify chat ID is correct in GitHub Secrets
3. Try sending `/help` — check bot responds

### "No alerts sent"

Alerts only run during **Vietnam trading hours** (Mon-Fri 09:00-11:30 and 13:00-15:00).
Try running outside these hours locally to verify the gate:
```bash
# Outside trading hours — should exit immediately
make run_alerts_once
```

### "ValueError: vnstock not installed"

The weekly/alerts workflows install vnstock automatically. Locally, install it:
```bash
pip3 install vnstock
```

### Tests fail locally

Ensure dependencies are installed:
```bash
pip3 install -r requirements.txt
make test
```

---

## Next Steps

1. **Daily check**: Send `/status` to bot every morning to track portfolio
2. **Weekly review**: Check Telegram digest every Sunday for new plan + guardrails warnings
3. **Customize**: Edit config files to change strategy, data source, or risk parameters
4. **Monitor**: Watch GitHub Actions tab to verify workflows run on schedule

---

## Commands Reference

| Command | Description |
|---------|-------------|
| `/buy SYMBOL QTY PRICE [asset=stock\|bond\|fund] [fee=N] [note=TEXT]` | Record a buy trade |
| `/sell SYMBOL QTY PRICE [asset=stock\|bond\|fund] [fee=N] [note=TEXT]` | Record a sell trade |
| `/setcash AMOUNT` | Set cash balance |
| `/status` | View portfolio & allocation |
| `/plan` | View current weekly plan |
| `/help` | Show all commands |

---

## Support

- **Issue**: Check [PLAN.md](PLAN.md) for architecture details
- **Code**: See [README.md](README.md) for how everything works
- **Tests**: Run `make test` to verify all 101 tests pass
