#!/usr/bin/env python3
"""Example usage of the updated gemini_analyzer.py with weekly trading focus."""

from datetime import datetime, timezone
from src.ai.gemini_analyzer import analyze_weekly_plan, AIAnalysis

# Example weekly trading recommendations
example_plan = {
    "recommendations": [
        {
            "symbol": "VHM",
            "action": "BUY",
            "entry_type": "BREAKOUT",
            "entry_price": 52500,
            "stop_loss": 50000,
            "take_profit": 58000,
            "rationale_bullets": [
                "Weekly MA10w (51200) > MA30w (48800) confirming uptrend",
                "RSI(14) = 68 showing breakout strength without overbought extreme",
                "Weekly close above 52000 resistance with T+1 entry confirmation",
                "ATR(14) = 1800, SL at 1.4x ATR distance from entry"
            ]
        },
        {
            "symbol": "VIC",
            "action": "BUY",
            "entry_type": "PULLBACK",
            "entry_price": 78500,
            "stop_loss": 75000,
            "take_profit": 85000,
            "rationale_bullets": [
                "Weekly uptrend intact with MA10w > MA30w",
                "RSI(14) = 42 after pullback from 87000 high",
                "Price touched ATR mid-zone (1.2x ATR from recent high)",
                "Risk/reward 1.86:1 with tick-step rounding (500đ increments)"
            ]
        },
        {
            "symbol": "FPT",
            "action": "HOLD",
            "rationale_bullets": [
                "Weekly trend still bullish but approaching resistance",
                "RSI(14) = 71 in overbought territory",
                "Waiting for pullback to ATR mid-zone for re-entry"
            ]
        }
    ]
}

portfolio_summary = """
Current portfolio: 60% cash, 40% stocks (VHM 15%, VIC 10%, FPT 15%)
Risk tolerance: Medium (max 2% position risk per trade)
Target: Weekly swing trades with 2-6 week holding periods
Focus: Large-cap Vietnamese stocks with good liquidity
"""

market_snapshot = """
VN-Index: 1,247 (+0.8% weekly)
Weekly volume: Above 20-day average
Sector rotation: Banks (-1.2%), Real estate (+2.1%), Technology (+1.8%)
Foreign flow: Net buying +$12M this week
Key resistance: VN-Index 1,260 level
"""

def main():
    print("=== Updated Gemini Analyzer Example ===\n")

    # Generate timestamp
    as_of = datetime.now(timezone.utc).isoformat()
    print(f"Analysis timestamp: {as_of}\n")

    # Test 1: With market snapshot
    print("🔹 Test 1: Analysis WITH market snapshot")
    analysis_with_market = analyze_weekly_plan(
        plan_dict=example_plan,
        portfolio_summary=portfolio_summary,
        as_of_timestamp=as_of,
        market_snapshot=market_snapshot
    )

    if analysis_with_market.generated:
        print("✅ AI Analysis generated successfully")
        print(f"Market context: {analysis_with_market.market_context}")
        print("\nScores:")
        for symbol, score in analysis_with_market.scores.items():
            print(f"  {symbol}: {score.score}/10 - {score.rationale}")
            if score.risk_note:
                print(f"    ⚠ {score.risk_note}")
    else:
        print("❌ AI Analysis failed or API key not available")

    print("\n" + "="*50 + "\n")

    # Test 2: Without market snapshot
    print("🔹 Test 2: Analysis WITHOUT market snapshot")
    analysis_no_market = analyze_weekly_plan(
        plan_dict=example_plan,
        portfolio_summary=portfolio_summary,
        as_of_timestamp=as_of,
        market_snapshot=""  # Empty market snapshot
    )

    if analysis_no_market.generated:
        print("✅ AI Analysis generated successfully")
        print(f"Market context: {analysis_no_market.market_context}")
        print("Should contain 'Insufficient market context' warning")
    else:
        print("❌ AI Analysis failed or API key not available")

    print("\n=== Expected Output Format ===")
    print("""
    {
      "scores": {
        "VHM": {
          "score": 8,
          "rationale": "Weekly MA10w > MA30w with RSI(14) at 68 showing breakout strength",
          "risk_note": ""
        },
        "VIC": {
          "score": 7,
          "rationale": "Good pullback setup with RSI(14) at 42 and ATR mid-zone touch",
          "risk_note": ""
        },
        "FPT": {
          "score": 5,
          "rationale": "HOLD appropriate with RSI(14) at 71 overbought level",
          "risk_note": "Overbought conditions suggest waiting for pullback"
        }
      },
      "market_context": "VN-Index showing weekly strength at +0.8% with real estate outperforming. Foreign net buying supports current uptrend."
    }
    """)

if __name__ == "__main__":
    main()