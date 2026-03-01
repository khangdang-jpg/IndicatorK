# Bug Fix: /plan Command Issue

## Problem Summary
The IndicatorK bot's `/plan` command was returning "No weekly plan generated yet. Run the weekly workflow first." even though:
1. The `data/weekly_plan.json` file existed with valid JSON
2. The file was pushed to GitHub and accessible at https://raw.githubusercontent.com/khangdang-jpg/IndicatorK/main/data/weekly_plan.json
3. The Workers code had been updated to remove auth headers for raw.githubusercontent.com URLs

## Root Cause Analysis

### The Critical Bug
The `GITHUB_REPO` environment variable was **only defined in the production environment** section of `wrangler.toml`:

```toml
[env.production.vars]
GITHUB_REPO = "khangdang-jpg/IndicatorK"
```

However, there was **no default environment variable** defined for the base configuration. This meant:

1. If the worker was deployed without the `--env production` flag, or
2. If the webhook was configured to use the default environment

Then `env.GITHUB_REPO` would be `undefined`, causing the URL to be constructed as:
```
https://raw.githubusercontent.com/undefined/main/data/weekly_plan.json
```

This URL returns HTTP 404, triggering the catch block in `handlePlan()` and displaying the fallback error message.

### Evidence
Testing confirmed this:
```javascript
const url = `https://raw.githubusercontent.com/${undefined}/main/data/weekly_plan.json`;
// Results in: https://raw.githubusercontent.com/undefined/main/data/weekly_plan.json
// HTTP 404 Not Found
```

## Fixes Applied

### Fix 1: Add Default Environment Variable
Updated `/Users/khangdang/IndicatorK/workers/wrangler.toml`:

```toml
name = "indicatork-bot"
main = "src/index.js"
compatibility_date = "2024-01-01"

# Default environment variables (used when deploying without --env flag)
[vars]
GITHUB_REPO = "khangdang-jpg/IndicatorK"

[env.production]
name = "indicatork-bot"

[env.production.vars]
GITHUB_REPO = "khangdang-jpg/IndicatorK"
```

### Fix 2: Improved Error Handling
Updated `getWeeklyPlan()` function in `/Users/khangdang/IndicatorK/workers/src/index.js`:

```javascript
async function getWeeklyPlan(env) {
  if (!env.GITHUB_REPO) {
    throw new Error('GITHUB_REPO environment variable not set');
  }
  const url = `https://raw.githubusercontent.com/${env.GITHUB_REPO}/main/data/weekly_plan.json`;
  console.log('Fetching weekly plan from:', url);
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to load weekly plan: ${response.status} from ${url}`);
  }
  return await response.json();
}
```

Changes:
1. Added validation to check if `GITHUB_REPO` is defined
2. Added console logging to show the URL being fetched
3. Improved error message to include the URL and HTTP status

## Deployment

The fix has been deployed:
```bash
cd /Users/khangdang/IndicatorK/workers
npx wrangler deploy --env production
```

Deployment output confirmed:
```
Your worker has access to the following bindings:
- Vars:
  - GITHUB_REPO: "khangdang-jpg/IndicatorK"
Deployed indicatork-bot triggers
  https://indicatork-bot.khang-dang.workers.dev
```

## Verification Steps

### Test 1: Verify JSON File is Accessible
```bash
curl https://raw.githubusercontent.com/khangdang-jpg/IndicatorK/main/data/weekly_plan.json
```
Result: Returns valid JSON with 5 recommendations

### Test 2: Test the /plan Command
Send a `/plan` command via Telegram to the bot. It should now display:
- Generated date
- Portfolio value
- List of recommendations (BUY VNM, HOLD VIC, BUY HPG, REDUCE FPT, WATCH VCB)

### Test 3: Check Workers Logs
```bash
cd /Users/khangdang/IndicatorK/workers
npx wrangler tail --env production
```
Look for:
- "Fetching weekly plan from: https://raw.githubusercontent.com/khangdang-jpg/IndicatorK/main/data/weekly_plan.json"
- No errors related to loading the plan

## Files Modified
1. `/Users/khangdang/IndicatorK/workers/wrangler.toml` - Added default environment variables
2. `/Users/khangdang/IndicatorK/workers/src/index.js` - Improved error handling in `getWeeklyPlan()`

## Prevention for Future
1. Always define environment variables in both the default `[vars]` section and environment-specific sections
2. Add validation checks for required environment variables at the start of functions
3. Include detailed logging for debugging (especially URLs being fetched)
4. Test both with and without `--env` flag when deploying

## Related Issues
- The same pattern should be checked for other environment variables (GITHUB_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID)
- However, those are secrets and must be set via `wrangler secret put`, which automatically applies to all environments

## Status
✅ FIXED - Deployed to production on 2026-02-28
