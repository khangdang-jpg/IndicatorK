"""Groq API integration for AI-powered stock analysis and scoring.

Uses Groq API with two-stage approach to provide:
  - Confidence scores (1-10) for each weekly recommendation
  - Brief Vietnamese-market-aware rationale per stock
  - Overall market context summary

Features:
  - Stage 1: llama-3.1-8b-instant for fast structured extraction (JSON)
  - Stage 2: llama-3.3-70b-versatile for final English digest
  - Caching and graceful fallbacks on API failures
  - Compatible with existing weekly workflow

Graceful degradation: all public functions return sensible defaults
if the API key is missing or a call fails. The system never breaks
without Groq.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Groq API configuration
_BASE_URL = "https://api.groq.com/openai/v1"
_MODEL_ANALYZE = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")  # For analysis
_TIMEOUT = 30  # seconds

# HTTP status codes that are fatal — don't retry
_FATAL_STATUS_CODES = {400, 401, 403, 404}

# Retry config for 429/timeout
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0   # seconds; doubles each attempt: 1s, 2s, 4s
_RETRY_AFTER_CAP = 60 # cap Retry-After header at 60s

# In-process cache: prompt_hash -> parsed result dict
# Prevents duplicate API calls within the same run
_CACHE: dict[str, dict] = {}

# Sentinel returned when retries exhausted on rate limit
_RATE_LIMITED = object()


@dataclass
class AIScore:
    """AI-generated score and rationale for a single recommendation."""
    symbol: str
    score: int  # 1-10 confidence
    rationale: str  # 1-sentence explanation
    risk_note: str = ""  # optional risk flag


@dataclass
class AIAnalysis:
    """Complete AI analysis for a weekly plan."""
    scores: dict[str, AIScore] = field(default_factory=dict)  # symbol -> AIScore
    market_context: str = ""  # overall VN market summary
    generated: bool = False  # True if AI actually ran


def get_api_key() -> Optional[str]:
    """Read Groq API key from environment."""
    return os.environ.get("GROQ_API_KEY")


def is_available() -> bool:
    """Check if Groq integration is configured."""
    return bool(get_api_key())


def _build_scoring_prompt(
    recommendations: list[dict],
    portfolio_summary: str,
    as_of: str = "",
) -> str:
    """Build analysis prompt for Groq API."""
    rec_lines = []
    for r in recommendations:
        rec_lines.append(
            f"- {r['symbol']}: {r['action']} | entry_type={r.get('entry_type', 'N/A')} | "
            f"entry={r.get('entry_price', 0):,.0f} | SL={r.get('stop_loss', 0):,.0f} | "
            f"TP={r.get('take_profit', 0):,.0f} | "
            f"rationale: {'; '.join(r.get('rationale_bullets', []))}"
        )
    rec_block = "\n".join(rec_lines)
    as_of_line = f"DATA AS OF: {as_of}\n" if as_of else ""

    return f"""Vietnamese stock analyst. Score these weekly recommendations using ONLY the data provided.
{as_of_line}
PORTFOLIO: {portfolio_summary}

RECOMMENDATIONS:
{rec_block}

For each symbol provide:
- score: 1-10 (technical setup + risk/reward ratio + entry type fit)
- rationale: exactly 1 sentence based on provided technicals only
- risk_note: 1 sentence if a specific risk is evident, else ""

Also provide market_context: 1 sentence summary based only on portfolio state above.

Respond ONLY with valid JSON, no markdown:
{{
  "scores": {{
    "SYMBOL": {{"score": 7, "rationale": "...", "risk_note": ""}}
  }},
  "market_context": "..."
}}"""


def _is_rate_limited(resp) -> bool:
    """Return True if the response is a rate-limit (429 or 503)."""
    if resp.status_code == 429:
        return True
    if resp.status_code == 503:
        try:
            body = resp.json()
            error_info = body.get("error", {})
            message = error_info.get("message", "").lower()
            if "rate limit" in message or "quota" in message:
                return True
        except (json.JSONDecodeError, AttributeError):
            pass
    return False


def _extract_retry_after(resp) -> float:
    """Extract Retry-After header from rate limit response."""
    retry_after = 0.0
    ra_header = resp.headers.get("Retry-After", "")
    if ra_header:
        try:
            retry_after = min(float(ra_header), _RETRY_AFTER_CAP)
        except ValueError:
            pass
    return retry_after


def _call_groq_with_retry(prompt: str, api_key: str) -> object:
    """Call Groq API with exponential-backoff retries on 429/timeout.

    Returns:
      - parsed dict on success
      - _RATE_LIMITED sentinel if all retries exhausted on 429
      - None on fatal or non-retriable error
    """
    import requests

    url = f"{_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": _MODEL_ANALYZE,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 800,
        "temperature": 0.3
    }

    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=_TIMEOUT,
            )

            logger.info("Groq API → HTTP %d | model=%s (attempt %d/%d)", resp.status_code, _MODEL_ANALYZE, attempt + 1, _MAX_RETRIES + 1)

            # Fatal errors - don't retry
            if resp.status_code in _FATAL_STATUS_CODES:
                try:
                    err_msg = resp.json().get("error", {}).get("message", resp.text[:200])
                except Exception:
                    err_msg = resp.text[:200]
                logger.error(
                    "🔑 FATAL HTTP %d | model=%s | %s",
                    resp.status_code, _MODEL_ANALYZE, err_msg,
                )
                logger.error("💡 Check: API key validity, model name, API enabled")
                return None

            # Rate limit - retry with backoff
            if _is_rate_limited(resp):
                retry_after = _extract_retry_after(resp)
                try:
                    err_msg = resp.json().get("error", {}).get("message", "(no message)")
                except Exception:
                    err_msg = "(no message)"

                if attempt < _MAX_RETRIES:
                    if retry_after > 0:
                        sleep_sec = retry_after
                        logger.warning(
                            "🚨 Rate limit | model=%s | %s | Retry-After=%ds → sleeping %ds (attempt %d/%d)",
                            _MODEL_ANALYZE, err_msg, retry_after, sleep_sec, attempt + 1, _MAX_RETRIES,
                        )
                    else:
                        sleep_sec = _BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.5)
                        logger.warning(
                            "🚨 Rate limit | model=%s | %s | backoff=%.1fs (attempt %d/%d)",
                            _MODEL_ANALYZE, err_msg, sleep_sec, attempt + 1, _MAX_RETRIES,
                        )
                    time.sleep(sleep_sec)
                    continue
                else:
                    logger.warning(
                        "🚨 Rate limit | model=%s | %s | retries exhausted",
                        _MODEL_ANALYZE, err_msg,
                    )
                    return _RATE_LIMITED

            resp.raise_for_status()

            data = resp.json()
            if "choices" not in data or not data["choices"]:
                logger.warning("❌ No choices in response | model=%s", _MODEL_ANALYZE)
                return None

            content = data["choices"][0]["message"]["content"]

            # Try to parse as JSON
            try:
                result = json.loads(content)
                logger.info("✅ Groq API succeeded | model=%s", _MODEL_ANALYZE)
                return result
            except json.JSONDecodeError as e:
                logger.warning("❌ Non-JSON response | model=%s: %s", _MODEL_ANALYZE, e)
                return None

        except requests.exceptions.Timeout:
            if attempt < _MAX_RETRIES:
                sleep_sec = _BACKOFF_BASE * (2 ** attempt)
                logger.warning("⏰ Timeout | model=%s — backoff %.1fs (attempt %d/%d)", _MODEL_ANALYZE, sleep_sec, attempt + 1, _MAX_RETRIES)
                time.sleep(sleep_sec)
                continue
            logger.warning("⏰ Timeout | model=%s — retries exhausted", _MODEL_ANALYZE)
            return None

        except requests.exceptions.RequestException as e:
            logger.warning("❌ Request error | model=%s: %s", _MODEL_ANALYZE, e)
            return None

        except Exception as e:
            logger.warning("❌ Unexpected error | model=%s: %s", _MODEL_ANALYZE, e)
            return None

    return None


def _call_groq(prompt: str, api_key: str) -> Optional[dict]:
    """Call Groq API with caching.

    Cache: responses are stored in _CACHE keyed by prompt hash so the same
    analysis is never requested twice in the same process run.
    """
    cache_key = hashlib.sha256(prompt.encode()).hexdigest()[:16]
    if cache_key in _CACHE:
        logger.info("📦 Groq cache hit (hash=%s) — skipping API call", cache_key)
        return _CACHE[cache_key]

    result = _call_groq_with_retry(prompt, api_key)

    if result is _RATE_LIMITED:
        logger.warning("🚨 Groq API rate-limited — AI analysis skipped")
        return None

    if result is None:
        # Fatal or parse error
        return None

    # Success — cache and return
    _CACHE[cache_key] = result
    return result


def analyze_weekly_plan(
    plan_dict: dict,
    portfolio_summary: str = "",
    as_of: str = "",
) -> AIAnalysis:
    """Score all recommendations in a weekly plan using Groq.

    Args:
        plan_dict: WeeklyPlan.to_dict() output
        portfolio_summary: short text describing portfolio state
        as_of: ISO timestamp string for the data snapshot (used as cache key component)

    Returns:
        AIAnalysis with scores and market context.
        Returns empty AIAnalysis(generated=False) on any failure.
    """
    api_key = get_api_key()
    if not api_key:
        logger.info("GROQ_API_KEY not configured — skipping AI analysis")
        return AIAnalysis()

    recommendations = plan_dict.get("recommendations", [])
    if not recommendations:
        return AIAnalysis(generated=True, market_context="No recommendations to analyze.")

    prompt = _build_scoring_prompt(recommendations, portfolio_summary, as_of)
    logger.info("Starting Groq analysis | model=%s recs=%d", _MODEL_ANALYZE, len(recommendations))
    result = _call_groq(prompt, api_key)

    if result is None:
        logger.warning("Groq analysis failed — returning empty analysis")
        return AIAnalysis()

    scores: dict[str, AIScore] = {}
    for sym, data in result.get("scores", {}).items():
        sym = sym.upper().strip()
        score_val = max(1, min(10, int(data.get("score", 5))))
        scores[sym] = AIScore(
            symbol=sym,
            score=score_val,
            rationale=str(data.get("rationale", "")),
            risk_note=str(data.get("risk_note", "")),
        )

    market_context = str(result.get("market_context", ""))
    logger.info("Groq scored %d/%d recommendations", len(scores), len(recommendations))
    return AIAnalysis(scores=scores, market_context=market_context, generated=True)


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
