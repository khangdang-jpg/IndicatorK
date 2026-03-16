#!/bin/bash

# Load environment variables
if [ -f ../.env ]; then
    source ../.env
fi

BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
WEBHOOK_URL="https://indicatork-bot.khang-dang.workers.dev"

if [ -z "$BOT_TOKEN" ]; then
    echo "Error: TELEGRAM_BOT_TOKEN not set"
    echo "Please set it in your .env file or export it as an environment variable"
    exit 1
fi

echo "Setting webhook to: $WEBHOOK_URL"

# Set webhook
curl -X POST "https://api.telegram.org/bot$BOT_TOKEN/setWebhook" \
  -H "Content-Type: application/json" \
  -d "{\"url\": \"$WEBHOOK_URL\"}"

echo -e "\n\nChecking webhook status:"
curl "https://api.telegram.org/bot$BOT_TOKEN/getWebhookInfo"

echo -e "\n\nWebhook setup complete!"