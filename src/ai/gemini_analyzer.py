"""Gemini API integration for AI-powered stock analysis and scoring.

Uses Google's Gemini free tier to provide:
  - Confidence scores (1-10) for each weekly recommendation
  - Brief Vietnamese-market-aware rationale per stock
  - Overall market context summary

Graceful degradation: all public functions return sensible defaults
if the API key is missing or a call fails. The system never breaks
without Gemini.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Gemini model for weekly stock analysis — using latest model
_DEFAULT_MODEL = "gemini-2.5-flash"

def _get_model() -> str:
    """Get model name with environment variable override support."""
    return os.environ.get("GEMINI_MODEL", _DEFAULT_MODEL)


def _clean_gemini_json(text: str) -> str:
    """Clean up common JSON issues in Gemini responses."""
    # Remove markdown code blocks if present
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]

    # Remove any leading/trailing whitespace and newlines
    text = text.strip()

    # Find JSON boundaries (first { to last })
    start_idx = text.find('{')
    end_idx = text.rfind('}')

    if start_idx == -1 or end_idx == -1:
        logger.warning("No valid JSON boundaries found in response")
        return "{}"

    json_text = text[start_idx:end_idx+1]

    # Fix common issues
    # Replace unescaped newlines in strings with \\n
    import re
    # This regex finds strings and replaces unescaped newlines within them
    def fix_newlines(match):
        string_content = match.group(0)
        # Replace unescaped newlines with escaped ones
        return string_content.replace('\n', '\\n').replace('\r', '\\r')

    # Apply newline fixes within quoted strings only
    try:
        json_text = re.sub(r'"[^"]*"', fix_newlines, json_text)
    except Exception:
        # If regex fails, just continue with original text
        pass

    return json_text
_API_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
_TIMEOUT = 30  # seconds


@dataclass
class AIScore:
    """AI-generated score and rationale for a single recommendation."""
    symbol: str
    score: int  # 1-10 confidence
    rationale: str  # 1-2 sentence explanation
    risk_note: str = ""  # optional risk flag


@dataclass
class AIAnalysis:
    """Complete AI analysis for a weekly plan."""
    scores: dict[str, AIScore] = field(default_factory=dict)  # symbol -> AIScore
    market_context: str = ""  # overall VN market summary
    generated: bool = False  # True if AI actually ran


def get_api_key() -> Optional[str]:
    """Read Gemini API key from environment."""
    return os.environ.get("GEMINI_API_KEY")


def is_available() -> bool:
    """Check if Gemini integration is configured."""
    return bool(get_api_key())


def _build_scoring_prompt(recommendations: list[dict], portfolio_summary: str,
                          as_of_timestamp: str = "", market_snapshot: str = "") -> str:
    """Build the prompt for Gemini to score recommendations.

    Args:
        recommendations: List of recommendation dictionaries
        portfolio_summary: Current portfolio state
        as_of_timestamp: When this analysis was generated (ISO format)
        market_snapshot: Optional current market context data
    """
    rec_lines = []
    for r in recommendations:
        # Extract technical indicators for weekly analysis
        rationale_text = '; '.join(r.get('rationale_bullets', []))
        rec_lines.append(
            f"- {r['symbol']}: {r['action']} | entry_type={r.get('entry_type', 'N/A')} | "
            f"entry={r.get('entry_price', 0):,.0f} | SL={r.get('stop_loss', 0):,.0f} | "
            f"TP={r.get('take_profit', 0):,.0f} | "
            f"rationale: {rationale_text}"
        )
    rec_block = "\n".join(rec_lines)

    # Build data context section
    data_context = f"PORTFOLIO:\n{portfolio_summary}\n\nRECOMMENDATIONS:\n{rec_block}"

    if as_of_timestamp:
        data_context = f"DATA AS OF: {as_of_timestamp}\n\n{data_context}"

    if market_snapshot:
        data_context += f"\n\nMARKET SNAPSHOT:\n{market_snapshot}"

    # Market context instruction based on data availability
    market_context_instruction = (
        "4. Write a 2-3 sentence overall Vietnamese market context summary using PROVIDED data only. "
        "If market snapshot not provided, state 'Insufficient market context for broader analysis.'"
        if not market_snapshot
        else "4. Write a 2-3 sentence overall Vietnamese market context summary based on the provided market snapshot."
    )

    return f"""You are a Vietnamese stock market analyst. Use ONLY the provided data below to analyze these weekly trading recommendations.

{data_context}

CRITICAL: Use ONLY the data provided above. Do not reference external knowledge or recent market events unless included in the input data.

WEEKLY TRADING SCORING CRITERIA (1-10):
1. Weekly trend alignment:
   - MA10w > MA30w for BUY signals (uptrend confirmation)
   - Price position relative to weekly moving averages
   - Weekly close confirmation vs intraday noise

2. Technical setup quality:
   - RSI(14) levels: oversold (<30) = pullback opportunity, overbought (>70) = breakout strength
   - ATR(14) context: entry timing relative to volatility
   - Breakout confirmation: T+1 earliest entry date after weekly close above resistance

3. Entry type suitability (Vietnamese market):
   - BREAKOUT: requires weekly close confirmation + volume
   - PULLBACK: requires ATR mid-zone touch (typically 1-1.5x ATR from recent high)
   - Tick-step rounding for Vietnamese stocks (500đ, 1000đ, etc.)

4. Risk/reward optimization:
   - SL distance vs ATR(14) - should be 1-2x ATR maximum
   - TP distance vs SL - minimum 1.5:1 ratio preferred
   - Position sizing considerations for Vietnamese market liquidity

INSTRUCTIONS:
1. Score each recommendation 1-10 using WEEKLY TRADING CRITERIA above.

2. Provide 1-sentence rationale focusing on weekly technical setup quality.

3. Flag risks: low liquidity, sector weakness, or poor risk/reward.

{market_context_instruction}

CRITICAL RESPONSE FORMAT:
- Output MUST be valid JSON only
- NO markdown backticks, NO ```json, NO extra text
- NO explanations before or after JSON
- If unsure about format, return: {{}}

EXACT FORMAT REQUIRED:
{{
  "scores": {{
    "SYMBOL": {{
      "score": 7,
      "rationale": "Weekly MA10w > MA30w with RSI(14) at 65 showing breakout strength",
      "risk_note": ""
    }}
  }},
  "market_context": "Market context based on provided data or 'Insufficient market context for broader analysis.'"
}}"""


def _call_gemini(prompt: str, api_key: str) -> Optional[dict]:
    """Make a single Gemini API call and parse the JSON response."""
    import requests

    url = _API_URL_TEMPLATE.format(model=_get_model())
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
        },
    }

    try:
        resp = requests.post(
            url,
            headers=headers,
            params={"key": api_key},
            json=payload,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()

        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]

        # Robust JSON parsing with cleanup for common Gemini issues
        cleaned_text = _clean_gemini_json(text)
        return json.loads(cleaned_text)

    except requests.exceptions.Timeout:
        logger.warning("Gemini API timeout after %ds", _TIMEOUT)
        return None
    except requests.exceptions.RequestException as e:
        logger.warning("Gemini API request failed: %s", e)
        return None
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        logger.warning("Failed to parse Gemini response: %s", e)
        return None


def analyze_weekly_plan(
    plan_dict: dict,
    portfolio_summary: str = "",
    as_of_timestamp: str = "",
    market_snapshot: str = "",
) -> AIAnalysis:
    """Score all recommendations in a weekly plan using Gemini.

    Args:
        plan_dict: WeeklyPlan.to_dict() output
        portfolio_summary: short text describing portfolio state
        as_of_timestamp: ISO timestamp when analysis was generated
        market_snapshot: optional current market context/data

    Returns:
        AIAnalysis with scores and market context.
        If API is unavailable or fails, returns an empty AIAnalysis
        with generated=False.
    """
    api_key = get_api_key()
    if not api_key:
        logger.info("Gemini API key not set — skipping AI analysis")
        return AIAnalysis()

    recommendations = plan_dict.get("recommendations", [])
    if not recommendations:
        return AIAnalysis(generated=True, market_context="No recommendations to analyze.")

    # Add current timestamp if not provided
    if not as_of_timestamp:
        from datetime import datetime, timezone
        as_of_timestamp = datetime.now(timezone.utc).isoformat()

    prompt = _build_scoring_prompt(recommendations, portfolio_summary, as_of_timestamp, market_snapshot)
    result = _call_gemini(prompt, api_key)

    if result is None:
        logger.warning("Gemini analysis failed — returning empty analysis")
        return AIAnalysis()

    # Parse scores
    scores: dict[str, AIScore] = {}
    raw_scores = result.get("scores", {})
    for sym, data in raw_scores.items():
        sym = sym.upper().strip()
        score_val = data.get("score", 5)
        # Clamp to 1-10
        score_val = max(1, min(10, int(score_val)))
        scores[sym] = AIScore(
            symbol=sym,
            score=score_val,
            rationale=str(data.get("rationale", "")),
            risk_note=str(data.get("risk_note", "")),
        )

    market_context = str(result.get("market_context", ""))

    logger.info("Gemini scored %d/%d recommendations", len(scores), len(recommendations))
    return AIAnalysis(
        scores=scores,
        market_context=market_context,
        generated=True,
    )


def format_ai_section(analysis: AIAnalysis, recommendations: list[dict]) -> str:
    """Format AI analysis as a Telegram message section.

    Returns empty string if AI analysis was not generated.
    """
    if not analysis.generated:
        return ""

    lines = ["", "*🤖 AI Analysis*"]

    if analysis.market_context:
        lines.append(f"_{analysis.market_context}_")
        lines.append("")

    # Show scores for BUY recommendations first, then others
    buys = [r for r in recommendations if r.get("action") == "BUY"]
    others = [r for r in recommendations if r.get("action") != "BUY"]

    for r in buys + others:
        sym = r["symbol"]
        ai = analysis.scores.get(sym)
        if not ai:
            continue

        bar = _score_bar(ai.score)
        lines.append(f"  `{sym}` {bar} {ai.score}/10")
        if ai.rationale:
            lines.append(f"    {ai.rationale}")
        if ai.risk_note:
            lines.append(f"    ⚠ {ai.risk_note}")

    return "\n".join(lines)


def _score_bar(score: int) -> str:
    """Visual score indicator."""
    if score >= 8:
        return "🟢"
    if score >= 6:
        return "🔵"
    if score >= 4:
        return "🟡"
    return "🔴"
