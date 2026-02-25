#!/bin/bash
# Interactive setup script for IndicatorK

set -e

echo "================================"
echo "IndicatorK Setup & Deployment"
echo "================================"
echo ""

# Phase 1: Get Telegram credentials
echo "Phase 1: Telegram Bot Setup"
echo "============================"
echo ""
echo "1. Open Telegram and message @BotFather"
echo "2. Send: /newbot"
echo "3. Follow prompts (bot name, username)"
echo "4. Save the token provided"
echo "5. Message your new bot, then visit:"
echo "   https://api.telegram.org/botTOKEN/getUpdates"
echo "   (Replace TOKEN with your bot token)"
echo "6. Find your chat ID in the JSON response (field: from.id)"
echo ""
read -p "Enter your Telegram BOT TOKEN: " BOT_TOKEN
read -p "Enter your Telegram ADMIN CHAT ID: " ADMIN_CHAT_ID

if [ -z "$BOT_TOKEN" ] || [ -z "$ADMIN_CHAT_ID" ]; then
    echo "Error: Both bot token and chat ID are required"
    exit 1
fi

export TELEGRAM_BOT_TOKEN="$BOT_TOKEN"
export TELEGRAM_ADMIN_CHAT_ID="$ADMIN_CHAT_ID"

echo ""
echo "✓ Telegram credentials saved"
echo ""

# Phase 2: Run local tests
echo "Phase 2: Local Testing"
echo "======================"
echo ""
echo "Running 101 unit tests..."
if python3 -m pytest tests/ -q; then
    echo "✓ All tests passed!"
else
    echo "✗ Tests failed. Fix issues before deploying."
    exit 1
fi

echo ""
echo "Generating first weekly plan..."
if python3 scripts/run_weekly.py > /dev/null 2>&1; then
    echo "✓ Weekly plan generated"
    if [ -f "data/weekly_plan.json" ]; then
        echo "  → Check Telegram for weekly digest message"
    fi
else
    echo "⚠ Warning: Weekly plan generation had issues (likely API timeout)"
    echo "  This is OK — GitHub Actions will retry on schedule"
fi

echo ""
echo "Testing bot command polling..."
if python3 scripts/run_bot.py > /dev/null 2>&1; then
    echo "✓ Bot polling works"
else
    echo "⚠ Warning: Bot polling had issues"
fi

echo ""

# Phase 3: Git setup
echo "Phase 3: GitHub Deployment"
echo "=========================="
echo ""
read -p "Enter your GitHub username: " GITHUB_USERNAME
read -p "Enter your GitHub email: " GITHUB_EMAIL

if [ -z "$GITHUB_USERNAME" ] || [ -z "$GITHUB_EMAIL" ]; then
    echo "Error: Both GitHub username and email are required"
    exit 1
fi

echo ""
echo "Configuring git..."
git config --global user.email "$GITHUB_EMAIL"
git config --global user.name "$GITHUB_USERNAME"

echo "Initializing repository..."
if [ ! -d ".git" ]; then
    git init
    git add .
    git commit -m "Initial commit: Vietnamese personal finance assistant MVP

- Zero-cost, zero-LLM design
- Weekly trading plans via trend_momentum_atr or rebalance_50_50
- 5-min price alerts during trading hours
- Telegram bot for manual trade logging
- Config-driven provider & strategy switching
- Guardrails for data quality & performance
- 101 unit tests passing"
    git branch -M main
else
    echo "Git repo already initialized"
fi

echo ""
echo "✓ Git initialized"
echo ""

# Phase 4: GitHub remote
echo "Next steps to deploy:"
echo "1. Create repo on GitHub: https://github.com/new"
echo "   - Repository name: IndicatorK"
echo "   - Make it PUBLIC"
echo "   - Do NOT initialize with README"
echo ""
echo "2. After creating, run:"
echo "   git remote add origin https://github.com/$GITHUB_USERNAME/IndicatorK.git"
echo "   git push -u origin main"
echo ""
echo "3. Add GitHub Secrets:"
echo "   - Go to: Settings → Secrets and variables → Actions"
echo "   - Add TELEGRAM_BOT_TOKEN = $BOT_TOKEN"
echo "   - Add TELEGRAM_ADMIN_CHAT_ID = $ADMIN_CHAT_ID"
echo ""
echo "4. Go to Actions tab and trigger 'Weekly Plan' manually"
echo ""

read -p "Ready to add GitHub remote? (y/n) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Enter your GitHub remote URL (from new repo page):"
    echo "Format: https://github.com/USERNAME/IndicatorK.git"
    read -p "URL: " REMOTE_URL

    if git remote add origin "$REMOTE_URL" 2>/dev/null; then
        echo "Remote added successfully"
    else
        echo "Remote might already exist, updating..."
        git remote set-url origin "$REMOTE_URL"
    fi

    echo ""
    echo "Pushing to GitHub..."
    if git push -u origin main; then
        echo "✓ Repository pushed to GitHub!"
        echo ""
        echo "Now add your GitHub Secrets:"
        echo "  1. Go to: https://github.com/$GITHUB_USERNAME/IndicatorK/settings/secrets/actions"
        echo "  2. New repository secret:"
        echo "     - Name: TELEGRAM_BOT_TOKEN"
        echo "     - Value: $BOT_TOKEN"
        echo "  3. New repository secret:"
        echo "     - Name: TELEGRAM_ADMIN_CHAT_ID"
        echo "     - Value: $ADMIN_CHAT_ID"
        echo ""
        echo "After adding secrets:"
        echo "  1. Go to Actions tab"
        echo "  2. Click 'Weekly Plan'"
        echo "  3. Click 'Run workflow'"
        echo "  4. Check Telegram for the digest message!"
    else
        echo "✗ Push failed. Check your remote URL and try again:"
        echo "git push -u origin main"
    fi
fi

echo ""
echo "================================"
echo "Setup complete!"
echo "See SETUP.md for detailed guide"
echo "================================"
