# IndicatorK - Quick Start Guide

## Your Vietnamese Personal Finance Trading Bot

**Status**: ✅ Production-ready with exceptional performance (28-47% CAGR, Sharpe 3.23)

## What It Does
- Generates trading plans every Sunday
- Sends price alerts every 5 minutes (trading hours)
- Accepts Telegram commands 24/7
- Tracks portfolio with FIFO accounting
- Costs $0/month (GitHub Actions + free APIs)

## Quick Setup
1. **Deploy**: Follow `docs/01_DEPLOYMENT_GUIDE.md`
2. **Commands**: See `docs/07_COMMANDS_REFERENCE.txt`
3. **Technical**: Check `docs/02_TECHNICAL_SETUP.md` if needed

## Key Files
- Strategy: `src/strategies/trend_momentum_atr_regime_adaptive.py`
- Config: `config/strategy.yml`, `config/risk.yml`
- Weekly workflow: `scripts/run_weekly.py`

## Documentation
Complete documentation in `docs/` directory - 10 comprehensive guides covering deployment, architecture, and implementation details.

---
*For detailed analysis and resolved issues, see `docs/analysis/`*