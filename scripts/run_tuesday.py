#!/usr/bin/env python3
"""Tuesday Tactical Signal Updates.

Enhanced intraweek signal generation on Tuesdays to capture mid-week
opportunities while reducing daily API quota usage.

This script generates tactical updates based on:
- Monday's market reaction to weekend news
- Tuesday morning momentum patterns
- Mid-week sector rotation signals
- Enhanced volatility breakout setups
"""

import logging
import sys
from datetime import date, timedelta
from pathlib import Path

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import get_provider, get_strategy, load_watchlist, get_risk_config

logger = logging.getLogger(__name__)


def generate_tuesday_tactical_signals():
    """Generate Tuesday tactical signals with enhanced intraweek focus."""
    logger.info("🗓️ TUESDAY TACTICAL SIGNAL GENERATION")
    logger.info("=" * 50)

    # Load system components
    provider = get_provider()
    strategy = get_strategy()
    symbols = load_watchlist()
    risk_config = get_risk_config()

    # Focus on enhanced intraweek signals if dual-stream
    if hasattr(strategy, 'intraweek_strategy'):
        logger.info(f"📊 Using enhanced intraweek component of {strategy.id}")
        intraweek_strategy = strategy.intraweek_strategy
    else:
        logger.info(f"📊 Using primary strategy: {strategy.id}")
        intraweek_strategy = strategy

    # Get Tuesday market data (focus on recent 5-10 days for intraweek)
    end_date = date.today()
    start_date = end_date - timedelta(days=15)  # More recent data for tactical signals

    logger.info(f"📈 Fetching tactical data for {len(symbols)} symbols ({start_date} to {end_date})")

    market_data = {}
    for symbol in symbols[:10]:  # Limit to top 10 for Tuesday tactical focus
        try:
            candles = provider.get_daily_history(symbol, start_date, end_date)
            if candles:
                market_data[symbol] = candles
                logger.info(f"   ✅ {symbol}: {len(candles)} candles")
        except Exception as e:
            logger.warning(f"   ❌ {symbol}: {e}")

    if not market_data:
        logger.error("No market data available for tactical signals")
        return

    # Generate tactical signals (placeholder portfolio state)
    from src.models import PortfolioState
    portfolio_state = PortfolioState(
        positions={},
        cash=20_000_000.0,  # 20M VND default
        total_value=20_000_000.0,
        allocation={"stock_pct": 0.0, "bond_fund_pct": 0.0, "cash_pct": 1.0},
        unrealized_pnl=0.0,
        realized_pnl=0.0
    )

    logger.info("🎯 Generating Tuesday tactical recommendations...")

    # Use the strategy to generate signals
    try:
        plan = intraweek_strategy.generate_weekly_plan(market_data, portfolio_state, risk_config)

        logger.info(f"📋 Generated {len(plan.recommendations)} tactical recommendations:")

        buy_signals = [r for r in plan.recommendations if r.action == "BUY"]
        for rec in buy_signals:
            logger.info(f"   🟢 BUY {rec.symbol}: {rec.position_target_pct:.1%} @ {rec.buy_zone_low:.0f}-{rec.buy_zone_high:.0f}")
            logger.info(f"      📍 Entry: {rec.entry_price:.0f} | SL: {rec.stop_loss:.0f} | TP: {rec.take_profit:.0f}")

        sell_signals = [r for r in plan.recommendations if r.action in ["SELL", "REDUCE"]]
        for rec in sell_signals:
            logger.info(f"   🔴 {rec.action} {rec.symbol}: {rec.position_target_pct:.1%}")

        # Save tactical update (separate from weekly plan)
        tactical_path = Path("data/tuesday_tactical_update.json")
        with open(tactical_path, "w") as f:
            import json
            json.dump(plan.to_dict(), f, indent=2)

        logger.info(f"💾 Tactical update saved to {tactical_path}")

    except Exception as e:
        logger.error(f"Failed to generate tactical signals: {e}")
        raise


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    try:
        generate_tuesday_tactical_signals()
        logger.info("✅ Tuesday tactical signal generation completed")
    except Exception as e:
        logger.error(f"❌ Tuesday tactical generation failed: {e}")
        sys.exit(1)