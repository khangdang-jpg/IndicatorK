#!/bin/bash
# Test script for Telegram credentials

export TELEGRAM_BOT_TOKEN="8620394249:AAEe209BkfQ_VaCBkhq6Xq0X34AWFxSX4LQ"
export TELEGRAM_ADMIN_CHAT_ID="6226624607"

echo "================================================"
echo "IndicatorK - Credential & Local Testing"
echo "================================================"
echo ""

echo "✅ Step 1: Credentials loaded"
echo "   Token length: ${#TELEGRAM_BOT_TOKEN}"
echo "   Chat ID: $TELEGRAM_ADMIN_CHAT_ID"
echo ""

echo "✅ Step 2: Running unit tests..."
cd /Users/khangdang/IndicatorK
python3 -m pytest tests/ -q --tb=short 2>&1 | tail -5
echo ""

echo "✅ Step 3: Testing weekly plan generation..."
echo "   This will fetch stock data and send a Telegram message..."
python3 scripts/run_weekly.py 2>&1 | grep -E "INFO|ERROR|Telegram|Success" | head -20
echo ""

echo "✅ Step 4: Check if Telegram message was received"
echo "   Go to your Telegram and check if you received the trading plan!"
echo ""

echo "================================================"
echo "Local testing complete!"
echo "Next: Push to GitHub and add secrets"
echo "================================================"
