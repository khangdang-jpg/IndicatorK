# Atomic Portfolio State Deployment Guide

## Overview

This deployment guide will help you migrate from the CSV-based portfolio tracking to the new atomic JSON state system, which provides:

- 🔒 **Race-condition protection** for simultaneous /buy and /sell commands
- 🔄 **Idempotency protection** against GitHub Actions retries
- 📊 **Single source of truth** for portfolio state
- 📝 **Complete audit trail** of all operations

## Pre-Deployment Checklist

- [ ] Backup current `data/` directory
- [ ] Verify GitHub Actions has `contents: write` permission
- [ ] Confirm Gemini API is working (check recent workflow runs)
- [ ] Test Cloudflare Worker is accessible

## Deployment Steps

### Step 1: Run Migration Script

```bash
# Create atomic state from current CSV data
python scripts/migrate_to_atomic_state.py
```

Expected output:
```
✅ Validation PASSED - Migration is accurate
Cash: CSV=10,000,000, Atomic=10,000,000, Diff=0
Positions: CSV=0, Atomic=0, Diff=0
```

### Step 2: Test the New System

```bash
# Validate atomic operations
python scripts/test_atomic_operations.py
```

Expected output:
```
🎉 All tests passed! The atomic portfolio system is ready.
```

### Step 3: Deploy Cloudflare Worker

1. **Replace the worker code:**
   ```bash
   # Backup current worker
   cp workers/src/index.js workers/src/index_backup.js

   # Deploy new atomic version
   cp workers/src/index_new.js workers/src/index.js
   cp workers/src/atomic_operations.js workers/src/atomic_operations.js
   ```

2. **Deploy to Cloudflare:**
   ```bash
   cd workers
   npx wrangler publish
   ```

3. **Verify deployment:**
   ```bash
   # Test with curl or browser
   curl -X GET https://your-worker.your-subdomain.workers.dev/
   # Should return: "IndicatorK Bot Command Gateway v2.0 (Atomic State)"
   ```

### Step 4: Test Commands

1. **Test /status command:**
   - Should show correct portfolio values
   - Should include sequence number and timestamp

2. **Test /setcash command:**
   ```
   /setcash 15000000 reason=test_deployment
   ```
   - Should update cash balance atomically
   - Should show confirmation message

3. **Test /buy command:**
   ```
   /buy VNM 100 65000
   ```
   - Should decrease cash, create position
   - Should show detailed confirmation

### Step 5: Enable GitHub Actions Integration

1. **Commit changes:**
   ```bash
   git add .
   git commit -m "🚀 DEPLOY: Atomic portfolio state system

   - Migrated from CSV to atomic JSON state
   - Added race-condition protection and locking
   - Implemented idempotency for GitHub Actions
   - Added comprehensive audit trail

   BREAKING CHANGE: Portfolio operations now atomic"
   git push
   ```

2. **Test weekly workflow:**
   ```bash
   gh workflow run weekly.yml
   ```

3. **Verify idempotency:**
   ```bash
   # Run again immediately - should skip with "already processed"
   gh workflow run weekly.yml
   ```

## Validation Checklist

### Portfolio State Consistency
- [ ] `/status` shows same values as before migration
- [ ] `/plan` shows correct total portfolio value
- [ ] AI analysis appears in weekly digest

### Atomic Operations
- [ ] `/buy` and `/sell` work correctly
- [ ] `/setcash` updates balance immediately
- [ ] Simultaneous commands don't cause conflicts

### GitHub Actions
- [ ] Weekly workflow runs without errors
- [ ] AI analysis populates in weekly_plan.json
- [ ] Idempotency prevents duplicate processing
- [ ] Files are committed back to repository

### Audit Trail
- [ ] `data/trades_log.jsonl` contains operation history
- [ ] Each operation has sequence numbers
- [ ] Timestamps are accurate

## Troubleshooting

### Common Issues

1. **"Portfolio state not found" error:**
   ```bash
   # Re-run migration script
   python scripts/migrate_to_atomic_state.py
   ```

2. **GitHub Actions permission denied:**
   - Verify workflow has `permissions: contents: write`
   - Check GitHub token has write access

3. **Cloudflare Worker timeout:**
   - Check worker logs in Cloudflare dashboard
   - Verify GitHub token is set in worker environment

4. **Lock timeout errors:**
   - Increase `LOCK_TIMEOUT_MS` in worker environment
   - Check for stuck locks in portfolio_state.json

### Emergency Rollback

If critical issues occur:

1. **Disable atomic state:**
   ```bash
   # In GitHub Actions environment
   export USE_ATOMIC_STATE=false
   ```

2. **Restore old worker:**
   ```bash
   cp workers/src/index_backup.js workers/src/index.js
   npx wrangler publish
   ```

3. **Continue with CSV system until issues resolved**

## Monitoring

After deployment, monitor:

- **Cloudflare Worker logs** for operation errors
- **GitHub Actions logs** for weekly workflow health
- **Portfolio consistency** between /status and weekly plans
- **Audit log growth** in trades_log.jsonl

## Support

If you encounter issues:

1. Check logs in Cloudflare Workers dashboard
2. Review GitHub Actions workflow logs
3. Validate portfolio_state.json structure
4. Run test_atomic_operations.py for diagnostics

The atomic state system provides robust portfolio management with strong consistency guarantees. Once deployed, all money operations will be protected against race conditions and data corruption.