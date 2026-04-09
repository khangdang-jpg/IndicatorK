#!/usr/bin/env python3
"""Thursday Risk Management and Weekly Preparation.

Enhanced risk management and weekly preparation on Thursdays to:
- Review mid-week performance vs targets
- Assess stop-loss and take-profit levels
- Prepare for weekend analysis and next week's plan
- Risk monitoring and position adjustments

Thursday is optimal because:
- 3 trading days of data since Monday
- Time to adjust before weekly close
- Preparation for weekend fundamental analysis
- Avoid Friday end-of-week volatility
"""

import logging
import sys
from datetime import date, timedelta
from pathlib import Path

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import get_provider, get_strategy, load_watchlist, get_risk_config

logger = logging.getLogger(__name__)


def run_thursday_risk_management():
    """Run Thursday risk management and weekly preparation."""
    logger.info("🛡️ THURSDAY RISK MANAGEMENT & WEEKLY PREP")
    logger.info("=" * 50)

    # Load system components
    provider = get_provider()
    strategy = get_strategy()
    symbols = load_watchlist()
    risk_config = get_risk_config()

    logger.info(f"📊 Strategy: {strategy.id} v{strategy.version}")

    # Load current weekly plan for risk assessment
    weekly_plan_path = Path("data/weekly_plan.json")
    current_positions = {}

    if weekly_plan_path.exists():
        try:
            import json
            with open(weekly_plan_path) as f:
                plan_data = json.load(f)

            buy_recs = [r for r in plan_data.get("recommendations", []) if r.get("action") == "BUY"]
            logger.info(f"📋 Found {len(buy_recs)} active BUY recommendations from weekly plan")

            for rec in buy_recs:
                current_positions[rec["symbol"]] = {
                    "entry_price": rec.get("entry_price", 0),
                    "stop_loss": rec.get("stop_loss", 0),
                    "take_profit": rec.get("take_profit", 0),
                    "position_pct": rec.get("position_target_pct", 0)
                }

        except Exception as e:
            logger.warning(f"Could not load weekly plan: {e}")

    if not current_positions:
        logger.info("📭 No active positions found for risk management")
        return

    # Get current market prices for risk assessment
    logger.info("💰 Fetching current prices for risk assessment...")

    end_date = date.today()
    start_date = end_date - timedelta(days=5)  # Recent data for current prices

    risk_assessments = []

    for symbol, position in current_positions.items():
        try:
            candles = provider.get_daily_history(symbol, start_date, end_date)
            if not candles:
                continue

            current_price = candles[-1].close
            entry_price = position["entry_price"]
            stop_loss = position["stop_loss"]
            take_profit = position["take_profit"]

            if entry_price > 0:
                # Calculate current PnL
                pnl_pct = (current_price - entry_price) / entry_price * 100

                # Calculate distances to key levels
                stop_distance = (current_price - stop_loss) / current_price * 100 if stop_loss > 0 else 0
                tp_distance = (take_profit - current_price) / current_price * 100 if take_profit > 0 else 0

                risk_assessment = {
                    "symbol": symbol,
                    "current_price": current_price,
                    "entry_price": entry_price,
                    "pnl_pct": pnl_pct,
                    "stop_distance_pct": stop_distance,
                    "tp_distance_pct": tp_distance,
                    "position_pct": position["position_pct"]
                }

                risk_assessments.append(risk_assessment)

                # Log assessment
                status = "🟢" if pnl_pct > 0 else "🔴"
                logger.info(f"{status} {symbol}: {current_price:.0f} | PnL: {pnl_pct:+.1f}% | SL: {stop_distance:.1f}% away | TP: {tp_distance:.1f}% away")

        except Exception as e:
            logger.warning(f"Could not assess {symbol}: {e}")

    # Risk management analysis
    logger.info("\n🎯 RISK MANAGEMENT ANALYSIS:")
    logger.info("-" * 40)

    if risk_assessments:
        # Overall portfolio metrics
        total_positions = len(risk_assessments)
        winners = [r for r in risk_assessments if r["pnl_pct"] > 0]
        losers = [r for r in risk_assessments if r["pnl_pct"] < 0]

        logger.info(f"📊 Portfolio: {len(winners)}/{total_positions} winners ({len(winners)/total_positions*100:.0f}%)")

        if winners:
            avg_winner = sum(r["pnl_pct"] for r in winners) / len(winners)
            logger.info(f"💰 Average winner: +{avg_winner:.1f}%")

        if losers:
            avg_loser = sum(r["pnl_pct"] for r in losers) / len(losers)
            logger.info(f"📉 Average loser: {avg_loser:.1f}%")

        # Risk alerts
        logger.info("\n⚠️ RISK ALERTS:")

        # Check positions near stop loss
        near_stop = [r for r in risk_assessments if 0 < r["stop_distance_pct"] < 2.0]  # Within 2% of stop
        if near_stop:
            logger.warning(f"🚨 {len(near_stop)} positions near stop loss:")
            for r in near_stop:
                logger.warning(f"   • {r['symbol']}: {r['stop_distance_pct']:.1f}% from SL")

        # Check positions near take profit
        near_tp = [r for r in risk_assessments if 0 < r["tp_distance_pct"] < 5.0]  # Within 5% of TP
        if near_tp:
            logger.info(f"🎯 {len(near_tp)} positions approaching take profit:")
            for r in near_tp:
                logger.info(f"   • {r['symbol']}: {r['tp_distance_pct']:.1f}% to TP")

        # Check for large positions
        large_positions = [r for r in risk_assessments if r["position_pct"] > 0.15]  # > 15%
        if large_positions:
            logger.warning(f"🏋️ {len(large_positions)} large positions (>15%):")
            for r in large_positions:
                logger.warning(f"   • {r['symbol']}: {r['position_pct']:.1%}")

    # Save risk assessment
    risk_report_path = Path("data/thursday_risk_assessment.json")
    with open(risk_report_path, "w") as f:
        import json
        json.dump({
            "assessment_date": date.today().isoformat(),
            "total_positions": len(risk_assessments),
            "risk_assessments": risk_assessments
        }, f, indent=2)

    logger.info(f"\n💾 Risk assessment saved to {risk_report_path}")

    # Weekend preparation notes
    logger.info("\n📝 WEEKEND PREPARATION CHECKLIST:")
    logger.info("   • Review economic calendar for next week")
    logger.info("   • Check earnings announcements")
    logger.info("   • Assess global market trends")
    logger.info("   • Prepare for Sunday weekly plan generation")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    try:
        run_thursday_risk_management()
        logger.info("✅ Thursday risk management completed")
    except Exception as e:
        logger.error(f"❌ Thursday risk management failed: {e}")
        sys.exit(1)