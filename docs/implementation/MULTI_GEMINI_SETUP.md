# 🚀 Multi-API Key Gemini Setup Guide

This guide explains how to configure multiple Gemini API keys for automatic failover when rate limits are hit.

## ✅ What Was Added

### 1. **Automatic Failover Logic**
- When the first API key hits a rate limit (HTTP 429), the system automatically switches to the second key
- Detailed logging shows which key is being used and when switches occur
- If all keys are rate limited, the system gracefully falls back to no AI analysis

### 2. **Environment Variables**
- `GEMINI_API_KEY` - Primary API key (existing)
- `GEMINI_API_KEY_2` - Secondary API key (new)

### 3. **Enhanced Logging**
```
✅ API key 1/2 (...0WLFx9ys) succeeded
🚨 API key 1/2 (...0WLFx9ys) RATE LIMIT (429) - switching to next API key
🔄 Automatically switching to API key 2
✅ API key 2/2 (...qLyzxIL8) succeeded
```

## 📋 Setup Instructions

### **For GitHub Actions (Production)**

1. Go to your GitHub repository
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Add the second API key:
   - Name: `GEMINI_API_KEY_2`
   - Value: `AIzaSyAw21CSIaZVourC7yMgzmohocEqLyzxIL8`
   - Click **Add secret**

### **For Local Development**

Add to your `.env` file (create if it doesn't exist):
```bash
# Primary Gemini API key (existing)
GEMINI_API_KEY=your_primary_key_here

# Secondary Gemini API key (new)
GEMINI_API_KEY_2=AIzaSyAw21CSIaZVourC7yMgzmohocEqLyzxIL8
```

Or export directly in your shell:
```bash
export GEMINI_API_KEY_2="AIzaSyAw21CSIaZVourC7yMgzmohocEqLyzxIL8"
```

## 🧪 Testing the Setup

Run the test script to verify everything is configured correctly:

```bash
python3 test_multi_gemini.py
```

Expected output for successful setup:
```
✅ SUCCESS: Multi-API failover is configured and ready!
   - Rate limit on key 1 → automatically tries key 2
   - Detailed logging shows which key is being used
   - Graceful fallback if all keys are rate limited
```

## 🔄 How Failover Works

### **Normal Operation (No Rate Limits)**
1. System uses primary key (`GEMINI_API_KEY`)
2. AI analysis succeeds
3. Weekly plan includes AI scores and context

### **Rate Limit Scenario**
1. System tries primary key → gets HTTP 429 (rate limit)
2. Logs: `🚨 API key 1/2 RATE LIMIT (429) - switching to next API key`
3. System automatically tries secondary key (`GEMINI_API_KEY_2`)
4. If successful: AI analysis continues normally
5. If secondary key also rate limited: graceful fallback (no AI scores)

### **All Keys Rate Limited**
1. System tries all available keys
2. Logs: `🚨 ALL API KEYS rate limited - AI analysis skipped`
3. Weekly plan shows rate limit notice in Telegram message
4. Core system continues working without AI scores

## 📊 Benefits

### **Increased Reliability**
- **2x capacity**: Two API keys = double the rate limit quota
- **Zero downtime**: Automatic switching prevents failed weekly plans
- **Transparent operation**: User doesn't notice when failover happens

### **Cost Efficient**
- Both keys can use Google's free tier
- No need for paid Gemini API subscriptions
- Rate limits reset independently

### **Production Ready**
- Handles edge cases (timeout, network errors, malformed responses)
- Detailed logging for troubleshooting
- Backward compatible (works with single API key)

## 🛠️ Files Modified

- `src/ai/gemini_analyzer.py` - Added multi-key logic and failover
- `.github/workflows/weekly.yml` - Added `GEMINI_API_KEY_2` environment variable
- `test_multi_gemini.py` - Test script to verify setup
- `MULTI_GEMINI_SETUP.md` - This documentation

## 🔧 Advanced Configuration

### **Using Different Models per Key**
The system uses the same model (`gemini-2.0-flash`) for both keys. To use different models:

```bash
# Override model globally
export GEMINI_MODEL="gemini-2.5-flash"
```

### **Adding More API Keys**
The current implementation supports 2 keys. To add more keys:
1. Modify `get_api_keys()` function in `src/ai/gemini_analyzer.py`
2. Add `GEMINI_API_KEY_3`, `GEMINI_API_KEY_4`, etc.
3. Update GitHub Actions workflow

## ✅ Deployment Status

- ✅ Code implemented and tested
- ✅ GitHub Actions workflow updated
- ✅ Backward compatible (single key still works)
- ✅ Test script provided
- ✅ Documentation complete

**Ready for deployment!** Just add the `GEMINI_API_KEY_2` secret to your GitHub repository.