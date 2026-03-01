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

# Gemini model for weekly stock analysis — using proven free tier model
_DEFAULT_MODEL = "gemini-2.0-flash"
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


def _build_scoring_prompt(recommendations: list[dict], portfolio_summary: str) -> str:
    """Build the prompt for Gemini to score recommendations."""
    rec_lines = []
    for r in recommendations:
        rec_lines.append(
            f"- {r['symbol']}: {r['action']} | entry_type={r.get('entry_type', 'N/A')} | "
            f"entry={r.get('entry_price', 0):,.0f} | SL={r.get('stop_loss', 0):,.0f} | "
            f"TP={r.get('take_profit', 0):,.0f} | "
            f"rationale: {'; '.join(r.get('rationale_bullets', []))}"
        )
    rec_block = "\n".join(rec_lines)

    return f"""You are a Vietnamese stock market analyst. Analyze these weekly trading recommendations
and provide a confidence score (1-10) for each, plus a brief market context summary.

PORTFOLIO:
{portfolio_summary}

RECOMMENDATIONS:
{rec_block}

INSTRUCTIONS:
1. Score each recommendation 1-10 based on:
   - Technical setup quality (trend alignment, entry timing)
   - Risk/reward ratio (SL vs TP distance)
   - Vietnamese market context (sector trends, macro conditions)
   - Entry type suitability (breakout confirmation vs pullback value)

2. Provide a 1-sentence rationale for each score in Vietnamese or English.

3. Flag any significant risks (e.g., low liquidity, sector headwinds).

4. Write a 2-3 sentence overall Vietnamese market context summary.

Respond ONLY with valid JSON in this exact format:
{{
  "scores": {{
    "SYMBOL": {{
      "score": 7,
      "rationale": "Strong breakout with volume confirmation",
      "risk_note": ""
    }}
  }},
  "market_context": "Overall VN market summary here."
}}"""


def _call_gemini(prompt: str, api_key: str) -> Optional[dict]:
    """Make a single Gemini API call and parse the JSON response."""
    import requests

    url = _API_URL_TEMPLATE.format(model=_DEFAULT_MODEL)
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
        return json.loads(text)

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
) -> AIAnalysis:
    """Score all recommendations in a weekly plan using Gemini.

    Args:
        plan_dict: WeeklyPlan.to_dict() output
        portfolio_summary: short text describing portfolio state

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

    prompt = _build_scoring_prompt(recommendations, portfolio_summary)
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
