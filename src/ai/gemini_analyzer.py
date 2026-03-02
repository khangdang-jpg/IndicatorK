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

import hashlib
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Gemini model — override via GEMINI_MODEL env var if needed
_DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
_API_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
_TIMEOUT = 30  # seconds

# HTTP status codes that are fatal — don't waste remaining API keys on these
_FATAL_STATUS_CODES = {400, 401, 403, 404}

# Retry config for 429/timeout
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0   # seconds; doubles each attempt: 1s, 2s, 4s
_RETRY_AFTER_CAP = 60 # cap Retry-After header at 60s

# In-process cache: prompt_hash -> parsed result dict
# Prevents duplicate API calls within the same run (e.g. retried weekly workflow)
_CACHE: dict[str, dict] = {}

# Sentinel returned by the per-key helper when it exhausts retries on 429
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


def get_api_keys() -> list[str]:
    """Read all available Gemini API keys from environment."""
    keys = []
    if key1 := os.environ.get("GEMINI_API_KEY"):
        keys.append(key1)
    if key2 := os.environ.get("GEMINI_API_KEY_2"):
        keys.append(key2)
    return keys


def get_api_key() -> Optional[str]:
    """Read primary Gemini API key from environment (legacy compatibility)."""
    keys = get_api_keys()
    return keys[0] if keys else None


def is_available() -> bool:
    """Check if Gemini integration is configured."""
    return bool(get_api_keys())


def _build_scoring_prompt(
    recommendations: list[dict],
    portfolio_summary: str,
    as_of: str = "",
) -> str:
    """Build a tight prompt — 1-sentence rationale, no macro unless provided."""
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

For each symbol output:
  score: 1-10 (technical setup + risk/reward ratio + entry type fit)
  rationale: exactly 1 sentence based on provided technicals only
  risk_note: 1 sentence if a specific risk is evident, else ""

Also output market_context: 1 sentence summary based only on portfolio state above.

Respond ONLY with valid JSON, no markdown:
{{
  "scores": {{
    "SYMBOL": {{"score": 7, "rationale": "...", "risk_note": ""}}
  }},
  "market_context": "..."
}}"""


def _is_rate_limited(resp) -> bool:
    """Return True if the response is a rate-limit (429 or 503 RESOURCE_EXHAUSTED)."""
    if resp.status_code == 429:
        return True
    if resp.status_code == 503:
        try:
            body = resp.json()
            error_info = body.get("error", {})
            status = error_info.get("status", "").upper()
            message = error_info.get("message", "").lower()
            if status == "RESOURCE_EXHAUSTED":
                return True
            if "quota" in message and ("exceeded" in message or "exhausted" in message):
                return True
            if "rate limit" in message:
                return True
        except (json.JSONDecodeError, AttributeError):
            logger.debug("Could not parse 503 response body for rate limit check")
    return False


def _extract_429_info(resp) -> tuple[str, float]:
    """Parse a rate-limit response for quota type and Retry-After seconds.

    Returns (quota_type_hint, retry_after_sec).

    Example log line produced by caller:
        🚨 key 1/2 (...xIL8) | 429 [RPM] | model=gemini-1.5-flash |
           Quota exceeded for quota metric 'generate_requests_per_minute' | backoff=1.3s (1/3)
    """
    # Retry-After header (Gemini sometimes sends it)
    retry_after = 0.0
    ra_header = resp.headers.get("Retry-After", "")
    if ra_header:
        try:
            retry_after = min(float(ra_header), _RETRY_AFTER_CAP)
        except ValueError:
            pass

    # Classify quota type from error message
    quota_type = "RPM/TPM"
    try:
        body = resp.json()
        msg = body.get("error", {}).get("message", "").lower()
        if "per day" in msg or "daily" in msg or "per_day" in msg:
            quota_type = "RPD"
        elif "tokens per minute" in msg or "tpm" in msg:
            quota_type = "TPM"
        elif "per minute" in msg or "rpm" in msg:
            quota_type = "RPM"
    except Exception:
        pass

    return quota_type, retry_after


def _call_key_with_retry(prompt: str, api_key: str, key_label: str) -> object:
    """Call one API key with exponential-backoff retries on 429/timeout.

    Returns:
      - parsed dict on success
      - _RATE_LIMITED sentinel if all retries exhausted on 429
      - None on fatal or non-retriable error
    """
    import requests

    url = _API_URL_TEMPLATE.format(model=_DEFAULT_MODEL)
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 512,           # reduced from 2048
            "responseMimeType": "application/json",
        },
    }

    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = requests.post(
                url,
                headers=headers,
                params={"key": api_key},
                json=payload,
                timeout=_TIMEOUT,
            )

            logger.info("%s → HTTP %d (attempt %d/%d)", key_label, resp.status_code, attempt + 1, _MAX_RETRIES + 1)

            # ── Fatal: bad key / model / permissions ──────────────────────
            if resp.status_code in _FATAL_STATUS_CODES:
                try:
                    err_msg = resp.json().get("error", {}).get("message", resp.text[:200])
                except Exception:
                    err_msg = resp.text[:200]
                logger.error(
                    "🔑 %s FATAL HTTP %d | model=%s | %s",
                    key_label, resp.status_code, _DEFAULT_MODEL, err_msg,
                )
                logger.error("💡 Check: API key validity, model name, API enabled in console")
                return None  # don't try other keys

            # ── Rate limit ────────────────────────────────────────────────
            if _is_rate_limited(resp):
                quota_type, retry_after = _extract_429_info(resp)
                try:
                    err_msg = resp.json().get("error", {}).get("message", "(no message)")
                except Exception:
                    err_msg = "(no message)"

                if attempt < _MAX_RETRIES:
                    if retry_after > 0:
                        sleep_sec = retry_after
                        logger.warning(
                            "🚨 %s | %d [%s] | model=%s | %s | Retry-After=%ds → sleeping %ds (attempt %d/%d)",
                            key_label, resp.status_code, quota_type, _DEFAULT_MODEL,
                            err_msg, retry_after, sleep_sec, attempt + 1, _MAX_RETRIES,
                        )
                    else:
                        sleep_sec = _BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.5)
                        logger.warning(
                            "🚨 %s | %d [%s] | model=%s | %s | backoff=%.1fs (attempt %d/%d)",
                            key_label, resp.status_code, quota_type, _DEFAULT_MODEL,
                            err_msg, sleep_sec, attempt + 1, _MAX_RETRIES,
                        )
                    time.sleep(sleep_sec)
                    continue
                else:
                    logger.warning(
                        "🚨 %s | %d [%s] | model=%s | %s | retries exhausted",
                        key_label, resp.status_code, quota_type, _DEFAULT_MODEL, err_msg,
                    )
                    return _RATE_LIMITED

            resp.raise_for_status()

            data = resp.json()
            if "candidates" not in data or not data["candidates"]:
                logger.warning("❌ %s no candidates in response", key_label)
                return None

            text = data["candidates"][0]["content"]["parts"][0]["text"]
            result = json.loads(text)
            logger.info("✅ %s succeeded", key_label)
            return result

        except requests.exceptions.Timeout:
            if attempt < _MAX_RETRIES:
                sleep_sec = _BACKOFF_BASE * (2 ** attempt)
                logger.warning("⏰ %s timeout — backoff %.1fs (attempt %d/%d)", key_label, sleep_sec, attempt + 1, _MAX_RETRIES)
                time.sleep(sleep_sec)
                continue
            logger.warning("⏰ %s timeout — retries exhausted", key_label)
            return None

        except requests.exceptions.RequestException as e:
            logger.warning("❌ %s request error: %s", key_label, e)
            return None

        except (KeyError, IndexError) as e:
            logger.warning("❌ %s unexpected response structure: %s", key_label, e)
            return None

        except json.JSONDecodeError as e:
            logger.warning("❌ %s non-JSON response (safety filter?): %s", key_label, e)
            return None

    return None


def _call_gemini(prompt: str, api_keys: list[str]) -> Optional[dict]:
    """Multi-key failover. Each key gets its own retry budget (_MAX_RETRIES).

    Cache: responses are stored in _CACHE keyed by prompt hash so the same
    analysis is never requested twice in the same process run.
    """
    cache_key = hashlib.sha256(prompt.encode()).hexdigest()[:16]
    if cache_key in _CACHE:
        logger.info("📦 Gemini cache hit (hash=%s) — skipping API call", cache_key)
        return _CACHE[cache_key]

    for i, api_key in enumerate(api_keys):
        key_label = f"key {i+1}/{len(api_keys)} (...{api_key[-8:]})"
        result = _call_key_with_retry(prompt, api_key, key_label)

        if result is _RATE_LIMITED:
            if i < len(api_keys) - 1:
                logger.info("🔄 Key %d rate-limited — failing over to key %d", i + 1, i + 2)
            else:
                logger.warning("🚨 ALL %d key(s) rate-limited — AI analysis skipped", len(api_keys))
            continue

        if result is None:
            # Fatal or parse error — stop trying (don't waste other keys on same bad prompt)
            return None

        # Success — cache and return
        _CACHE[cache_key] = result
        return result

    return None


def analyze_weekly_plan(
    plan_dict: dict,
    portfolio_summary: str = "",
    as_of: str = "",
) -> AIAnalysis:
    """Score all recommendations in a weekly plan using Gemini.

    Args:
        plan_dict: WeeklyPlan.to_dict() output
        portfolio_summary: short text describing portfolio state
        as_of: ISO timestamp string for the data snapshot (used as cache key component)

    Returns:
        AIAnalysis with scores and market context.
        Returns empty AIAnalysis(generated=False) on any failure.
    """
    api_keys = get_api_keys()
    if not api_keys:
        logger.info("No Gemini API keys configured — skipping AI analysis")
        return AIAnalysis()

    recommendations = plan_dict.get("recommendations", [])
    if not recommendations:
        return AIAnalysis(generated=True, market_context="No recommendations to analyze.")

    prompt = _build_scoring_prompt(recommendations, portfolio_summary, as_of)
    logger.info("Starting Gemini analysis | model=%s keys=%d recs=%d", _DEFAULT_MODEL, len(api_keys), len(recommendations))
    result = _call_gemini(prompt, api_keys)

    if result is None:
        logger.warning("Gemini analysis failed — returning empty analysis")
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
    logger.info("Gemini scored %d/%d recommendations", len(scores), len(recommendations))
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
