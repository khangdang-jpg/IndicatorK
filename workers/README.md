# IndicatorK Bot - Cloudflare Workers Command Gateway

This is a lightweight Cloudflare Workers implementation that provides instant webhook responses for Telegram bot commands while keeping the heavy batch processing on GitHub Actions.

## Features

- ✅ **Instant bot responses** (vs 0-5 minute GitHub Actions polling)
- ✅ **Minimal scope** - only handles commands, not batch processing
- ✅ **Shared state** - reads/writes same GitHub repo files
- ✅ **Zero cost** - free tier sufficient for personal use

## Supported Commands

- `/buy SYMBOL QTY PRICE [fee=N] [note=TEXT]` - Record buy trade
- `/sell SYMBOL QTY PRICE [fee=N] [note=TEXT]` - Record sell trade
- `/setcash AMOUNT` - Set cash balance
- `/status` - View portfolio positions
- `/plan` - View current weekly plan
- `/help` - Show help message

## Setup & Deployment

### 1. Install Wrangler CLI

```bash
npm install -g wrangler
wrangler login
```

### 2. Configure Environment

Edit `wrangler.toml` and set your GitHub repo:

```toml
[env.production.vars]
GITHUB_REPO = "your-username/IndicatorK"
```

### 3. Set Secrets

```bash
# Set required secrets
wrangler secret put TELEGRAM_BOT_TOKEN
wrangler secret put TELEGRAM_ADMIN_CHAT_ID
wrangler secret put GITHUB_TOKEN
```

**GitHub Token Requirements:**
- Create a Personal Access Token with `repo` scope
- Needs read/write access to repository contents

### 4. Deploy to Cloudflare

```bash
npm install
wrangler deploy
```

### 5. Configure Telegram Webhook

Replace the existing long-polling with webhook:

```bash
# Set webhook URL (use your actual Workers URL)
curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://indicatork-bot.your-subdomain.workers.dev/"}'

# Verify webhook is set
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo"
```

### 6. Disable GitHub Actions Bot Polling

Comment out or remove the `bot.yml` workflow:

```bash
# Rename to disable
mv .github/workflows/bot.yml .github/workflows/bot.yml.disabled
```

Keep `alerts.yml` and `weekly.yml` unchanged - they continue running the batch processing.

## Architecture

```
┌─ Real-time Commands ────────────────────────┐
│  Telegram → CF Workers webhook              │  ← INSTANT
│  /buy, /sell, /status, /plan, /help        │
│  Reads/writes GitHub repo via API          │
└─────────────────────────────────────────────┘
            ↕️ (Shared State)
┌─ Batch Processing ──────────────────────────┐
│  GitHub Actions (unchanged)                 │  ← STAYS AS-IS
│  • Weekly plan generation                   │
│  • Price alerts every 5min                  │
│  • All heavy lifting (vnstock, indicators)  │
└─────────────────────────────────────────────┘
```

## Benefits

| Before (GitHub Actions) | After (Hybrid) |
|------------------------|----------------|
| 0-5 minute command delay | Instant response |
| Free compute | Still free (Workers free tier) |
| Git-based state | Same shared state |
| All-or-nothing polling | Real-time commands + batch jobs |

## Development

```bash
# Local development
npm run dev

# View logs
npm run tail

# Deploy
npm run deploy
```

## Troubleshooting

### Commands not working?
1. Check webhook is set: `curl "https://api.telegram.org/bot$TOKEN/getWebhookInfo"`
2. Check Workers logs: `wrangler tail`
3. Verify secrets are set: `wrangler secret list`

### GitHub API errors?
1. Ensure `GITHUB_TOKEN` has `repo` scope
2. Verify `GITHUB_REPO` format: `username/repository-name`
3. Check repository permissions

### State conflicts?
The Workers and GitHub Actions both read/write the same files. The GitHub Contents API handles concurrent access, but avoid running commands during workflow execution for best results.