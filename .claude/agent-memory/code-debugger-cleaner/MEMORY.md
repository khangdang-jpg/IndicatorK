# Code Debugger & Cleaner Memory - IndicatorK Project

## Common Bug Patterns

### Cloudflare Workers Environment Variables
**Pattern**: Environment variables undefined at runtime even though they're configured in wrangler.toml

**Root Cause**: Variables defined only in `[env.production.vars]` are NOT available to default environment deployments

**Solution**: Always define variables in both places:
```toml
# Default environment
[vars]
MY_VAR = "value"

# Production environment
[env.production.vars]
MY_VAR = "value"
```

**Location**: `/Users/khangdang/IndicatorK/workers/wrangler.toml`

**Example Bug**: `/plan` command failed because `env.GITHUB_REPO` was undefined, causing URL construction to fail with `https://raw.githubusercontent.com/undefined/...`

### String Interpolation with Undefined Values
**Pattern**: Template literals with undefined values create invalid URLs/paths

**Detection**: Add validation before using environment variables:
```javascript
if (!env.REQUIRED_VAR) {
  throw new Error('REQUIRED_VAR environment variable not set');
}
```

## Project Structure

### Key Files
- `/Users/khangdang/IndicatorK/workers/src/index.js` - Main Workers code
- `/Users/khangdang/IndicatorK/workers/wrangler.toml` - Workers configuration
- `/Users/khangdang/IndicatorK/data/weekly_plan.json` - Weekly trading plan
- `/Users/khangdang/IndicatorK/data/trades.csv` - Trading history

### Deployment
- Production URL: https://indicatork-bot.khang-dang.workers.dev
- Deploy command: `cd workers && npx wrangler deploy --env production`
- Always use `--env production` flag for production deployments

## Debugging Techniques

### Cloudflare Workers Debugging
1. Check environment variables: Look at deployment output for "bindings" section
2. View logs: `npx wrangler tail --env production`
3. Test locally: Create Node.js test scripts to simulate Workers environment
4. Verify URLs: Test with curl/WebFetch before assuming Workers has access

### Error Handling Best Practices
- Add specific validation for undefined environment variables
- Log URLs and paths being accessed for easier debugging
- Include context in error messages (HTTP status, URL, etc.)
- Don't rely solely on catch blocks - validate inputs first

## Fixed Issues
- 2026-02-28: /plan command returning "no weekly plan" error - Fixed undefined GITHUB_REPO variable
