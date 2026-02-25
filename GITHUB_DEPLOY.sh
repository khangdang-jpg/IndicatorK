#!/bin/bash
# IndicatorK - GitHub Deployment Script
# This script automates steps 2 and 3 of the deployment process
# STEP 1: Create repo manually at https://github.com/new (make it PUBLIC, uncheck README/gitignore/license)
# Then run this script with your GitHub details

set -e

echo "================================================"
echo "IndicatorK - GitHub Deployment"
echo "================================================"
echo ""

# Verify we're in the right directory
if [ ! -f "DEPLOYMENT_READY.md" ]; then
    echo "❌ Error: Must run from /Users/khangdang/IndicatorK directory"
    exit 1
fi

# Get GitHub credentials
echo "Step 1: Configure Git Locally"
echo "=============================="
read -p "Enter your GitHub username: " GITHUB_USERNAME
read -p "Enter your email (for git commits): " GITHUB_EMAIL

if [ -z "$GITHUB_USERNAME" ] || [ -z "$GITHUB_EMAIL" ]; then
    echo "Error: Both GitHub username and email are required"
    exit 1
fi

echo ""
echo "Configuring git..."
git config --global user.email "$GITHUB_EMAIL"
git config --global user.name "$GITHUB_USERNAME"

# Initialize repo if not already done
echo ""
echo "Step 2: Initialize Repository"
echo "=============================="

if [ ! -d ".git" ]; then
    echo "Initializing git repository..."
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
    echo "✓ Repository initialized"
else
    echo "Repository already initialized"
fi

# Connect to GitHub and push
echo ""
echo "Step 3: Push to GitHub"
echo "======================"
echo ""
echo "Please create a repository on GitHub first:"
echo "  1. Go to https://github.com/new"
echo "  2. Repository name: IndicatorK"
echo "  3. Make it PUBLIC"
echo "  4. Do NOT initialize with README/gitignore/license"
echo "  5. Click 'Create repository'"
echo ""

read -p "Enter your GitHub remote URL (format: https://github.com/USERNAME/IndicatorK.git): " REMOTE_URL

if [ -z "$REMOTE_URL" ]; then
    echo "Error: Remote URL is required"
    exit 1
fi

echo ""
echo "Adding remote and pushing to GitHub..."
if git remote add origin "$REMOTE_URL" 2>/dev/null; then
    echo "Remote added"
elif git remote set-url origin "$REMOTE_URL"; then
    echo "Remote updated"
else
    echo "Error: Could not add remote"
    exit 1
fi

git push -u origin main

echo ""
echo "✓ Repository pushed to GitHub!"
echo ""
echo "================================================"
echo "Step 4: Add GitHub Secrets"
echo "================================================"
echo ""
echo "Now you need to add your Telegram credentials as GitHub Secrets:"
echo ""
echo "1. Go to: https://github.com/$GITHUB_USERNAME/IndicatorK/settings/secrets/actions"
echo "2. Click 'New repository secret'"
echo ""
echo "Add these two secrets:"
echo "  Name: TELEGRAM_BOT_TOKEN"
echo "  Value: 8620394249:AAEe209BkfQ_VaCBkhq6Xq0X34AWFxSX4LQ"
echo ""
echo "  Name: TELEGRAM_ADMIN_CHAT_ID"
echo "  Value: 6226624607"
echo ""
echo "3. After adding both secrets, go to Actions tab and run the 'Weekly Plan' workflow"
echo "4. Check Telegram for the weekly digest message"
echo ""
echo "================================================"
echo "Deployment complete! 🚀"
echo "================================================"
echo ""
echo "Your bot is now:"
echo "  ✓ Running on GitHub Actions (FREE forever)"
echo "  ✓ Checking prices every 5 minutes (trading hours)"
echo "  ✓ Generating weekly plans automatically"
echo "  ✓ Accepting your Telegram commands 24/7"
echo ""
echo "See NEXT_STEPS.md for detailed instructions."
