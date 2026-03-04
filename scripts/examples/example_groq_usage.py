#!/usr/bin/env python3
"""Example usage of the updated Groq-based analyzer for weekly trading focus."""

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
    print("=== Groq API Analyzer Example ===\n")

    # Generate timestamp
    as_of = datetime.now(timezone.utc).isoformat()
    print(f"Analysis timestamp: {as_of}\n")

    # Test 1: Basic analysis
    print("🔹 Test 1: Basic Groq analysis")
    analysis = analyze_weekly_plan(
        plan_dict=example_plan,
        portfolio_summary=portfolio_summary,
        as_of=as_of
    )

    if analysis.generated:
        print("✅ AI Analysis generated successfully")
        print(f"Market context: {analysis.market_context}")
        print("\nScores:")
        for symbol, score in analysis.scores.items():
            print(f"  {symbol}: {score.score}/10 - {score.rationale}")
            if score.risk_note:
                print(f"    ⚠ {score.risk_note}")
    else:
        print("❌ AI Analysis failed or API key not available")
        print("💡 Make sure GROQ_API_KEY environment variable is set")

    print("\n" + "="*50 + "\n")

    # Test 2: API availability check
    print("🔹 Test 2: API availability check")
    from src.ai.gemini_analyzer import is_available

    if is_available():
        print("✅ Groq API key is configured")
    else:
        print("❌ Groq API key not found")
        print("💡 Set GROQ_API_KEY environment variable to enable AI analysis")

    print("\n=== Expected Output Format ===")
    print("""
    {
      "scores": {
        "VHM": {
          "score": 8,
          "rationale": "Strong weekly trend with good technical setup and entry confirmation",
          "risk_note": ""
        },
        "VIC": {
          "score": 7,
          "rationale": "Solid pullback opportunity with favorable risk/reward ratio",
          "risk_note": "Monitor for volume confirmation on entry"
        },
        "FPT": {
          "score": 5,
          "rationale": "HOLD appropriate with overbought conditions requiring patience",
          "risk_note": "Wait for pullback before considering new entry"
        }
      },
      "market_context": "Vietnamese market showing weekly strength with positive institutional flow."
    }
    """)

if __name__ == "__main__":
    main()