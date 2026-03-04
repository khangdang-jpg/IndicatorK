"""Groq API integration for AI-powered stock analysis and scoring.

Uses Groq's API with two-stage approach:
  - Stage 1: llama-3.1-8b-instant for structured news extraction (JSON)
  - Stage 2: llama-3.3-70b-versatile for final English digest composition

Features:
  - Caching by (symbol, news_hash) in data/news_cache.json
  - Graceful fallbacks on API failures/429s
  - Basic retry/backoff for rate limits
  - OpenAI-compatible API usage
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Groq API configuration
_BASE_URL = "https://api.groq.com/openai/v1"
_MODEL_EXTRACT = "llama-3.1-8b-instant"  # Fast structured extraction
_MODEL_DIGEST = "llama-3.3-70b-versatile"  # Final English composition
_TIMEOUT = 30  # seconds
_CACHE_FILE = "data/news_cache.json"

# HTTP status codes that are fatal — don't waste time retrying
_FATAL_STATUS_CODES = {400, 401, 403, 404}

# Retry config for 429/timeout
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0   # seconds; doubles each attempt: 1s, 2s, 4s
_RETRY_AFTER_CAP = 60 # cap Retry-After header at 60s

# In-process cache: prompt_hash -> parsed result dict
# Prevents duplicate API calls within the same run
_CACHE: dict[str, dict] = {}


@dataclass
class NewsScore:
    """AI-generated score and rationale for a single news item."""
    symbol: str
    sentiment: str  # "bullish", "bearish", "neutral"
    impact: float   # 0.0-1.0 impact strength
    confidence: float  # 0.0-1.0 confidence in analysis
    summary: str    # Brief summary of the news impact
    source: str = ""  # News source if available


@dataclass
class NewsAnalysis:
    """Complete AI analysis for news items."""
    scores: dict[str, list[NewsScore]] = field(default_factory=dict)  # symbol -> [NewsScore]
    overall_sentiment: str = "neutral"  # Overall market sentiment
    generated: bool = False  # True if AI actually ran
    cache_hit: bool = False  # True if result came from cache


def get_api_key() -> Optional[str]:
    """Read Groq API key from environment."""
    return os.environ.get("GROQ_API_KEY")


def is_available() -> bool:
    """Check if Groq integration is configured."""
    return bool(get_api_key())


def _load_cache() -> dict:
    """Load news cache from disk."""
    cache_path = Path(_CACHE_FILE)
    if not cache_path.exists():
        return {}

    try:
        with open(cache_path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        logger.warning(f"Could not load cache from {_CACHE_FILE}")
        return {}


def _save_cache(cache_data: dict) -> None:
    """Save news cache to disk."""
    cache_path = Path(_CACHE_FILE)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(cache_path, 'w') as f:
            json.dump(cache_data, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not save cache to {_CACHE_FILE}: {e}")


def _hash_news_items(news_items: list[dict]) -> str:
    """Generate hash for news items for caching."""
    content = json.dumps(news_items, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


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
    """Parse Retry-After header from rate limit response."""
    retry_after = 0.0
    ra_header = resp.headers.get("Retry-After", "")
    if ra_header:
        try:
            retry_after = min(float(ra_header), _RETRY_AFTER_CAP)
        except ValueError:
            pass
    return retry_after


def _call_groq_with_retry(
    prompt: str,
    model: str,
    api_key: str,
    max_tokens: int = 512,
    temperature: float = 0.3
) -> Optional[dict]:
    """Call Groq API with exponential backoff retries on 429/timeout."""
    import requests

    url = f"{_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature
    }

    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=_TIMEOUT,
            )

            logger.info(f"Groq API → HTTP {resp.status_code} | model={model} (attempt {attempt + 1}/{_MAX_RETRIES + 1})")

            # Fatal errors - don't retry
            if resp.status_code in _FATAL_STATUS_CODES:
                try:
                    err_msg = resp.json().get("error", {}).get("message", resp.text[:200])
                except Exception:
                    err_msg = resp.text[:200]
                logger.error(
                    f"🔑 FATAL HTTP {resp.status_code} | model={model} | {err_msg}"
                )
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
                            f"🚨 Rate limit | model={model} | {err_msg} | Retry-After={retry_after}s → sleeping {sleep_sec}s (attempt {attempt + 1}/{_MAX_RETRIES})"
                        )
                    else:
                        sleep_sec = _BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.5)
                        logger.warning(
                            f"🚨 Rate limit | model={model} | {err_msg} | backoff={sleep_sec:.1f}s (attempt {attempt + 1}/{_MAX_RETRIES})"
                        )
                    time.sleep(sleep_sec)
                    continue
                else:
                    logger.warning(
                        f"🚨 Rate limit | model={model} | {err_msg} | retries exhausted"
                    )
                    return None

            resp.raise_for_status()

            data = resp.json()
            if "choices" not in data or not data["choices"]:
                logger.warning(f"❌ No choices in response | model={model}")
                return None

            content = data["choices"][0]["message"]["content"]

            # Try to parse as JSON for structured responses
            try:
                result = json.loads(content)
                logger.info(f"✅ Groq API succeeded | model={model}")
                return result
            except json.JSONDecodeError:
                # For digest composition, return plain text
                logger.info(f"✅ Groq API succeeded (text) | model={model}")
                return {"content": content}

        except requests.exceptions.Timeout:
            if attempt < _MAX_RETRIES:
                sleep_sec = _BACKOFF_BASE * (2 ** attempt)
                logger.warning(f"⏰ Timeout | model={model} — backoff {sleep_sec:.1f}s (attempt {attempt + 1}/{_MAX_RETRIES})")
                time.sleep(sleep_sec)
                continue
            logger.warning(f"⏰ Timeout | model={model} — retries exhausted")
            return None

        except requests.exceptions.RequestException as e:
            logger.warning(f"❌ Request error | model={model}: {e}")
            return None

        except Exception as e:
            logger.warning(f"❌ Unexpected error | model={model}: {e}")
            return None

    return None


def _build_extraction_prompt(news_items: list[dict]) -> str:
    """Build prompt for news extraction stage."""
    news_lines = []
    for item in news_items:
        symbol = item.get("symbol", "UNKNOWN")
        title = item.get("title", "")
        summary = item.get("summary", "")[:200]  # Limit length
        source = item.get("source", "")

        news_lines.append(
            f"- {symbol}: {title}\n  Source: {source}\n  Summary: {summary}"
        )

    news_block = "\n".join(news_lines)

    return f"""Vietnamese stock market analyst. Analyze these news items and extract sentiment scores.

NEWS ITEMS:
{news_block}

For each news item, determine:
- sentiment: "bullish", "bearish", or "neutral"
- impact: 0.0-1.0 (how much this news could move the stock)
- confidence: 0.0-1.0 (confidence in your analysis)
- summary: One sentence about the news impact

Also determine overall_sentiment for the market: "bullish", "bearish", or "neutral"

Respond ONLY with valid JSON, no markdown:
{{
  "scores": {{
    "SYMBOL": [{{
      "symbol": "SYMBOL",
      "sentiment": "bullish",
      "impact": 0.7,
      "confidence": 0.8,
      "summary": "Brief impact summary",
      "source": "news source"
    }}]
  }},
  "overall_sentiment": "neutral"
}}"""


def _build_digest_prompt(plan: dict, news_scores: dict) -> str:
    """Build prompt for weekly digest composition."""
    # Extract key info from plan
    recs = plan.get("recommendations", [])
    buy_symbols = [r["symbol"] for r in recs if r.get("action") == "BUY"]
    hold_symbols = [r["symbol"] for r in recs if r.get("action") in ["HOLD", "REDUCE"]]

    # Format news scores
    news_summary = []
    for symbol, scores in news_scores.get("scores", {}).items():
        if scores:  # Take first score for each symbol
            score = scores[0]
            news_summary.append(
                f"- {symbol}: {score['sentiment']} (impact: {score['impact']:.1f}, confidence: {score['confidence']:.1f}) - {score['summary']}"
            )

    news_block = "\n".join(news_summary) if news_summary else "No relevant news analysis available."
    overall_sentiment = news_scores.get("overall_sentiment", "neutral")

    return f"""You are composing a weekly Vietnamese stock market digest. Write a brief, professional summary in English.

TRADING PLAN:
- BUY signals: {', '.join(buy_symbols) if buy_symbols else 'None'}
- HOLD positions: {', '.join(hold_symbols) if hold_symbols else 'None'}

NEWS SENTIMENT ANALYSIS:
Overall market sentiment: {overall_sentiment}
{news_block}

Write a concise weekly digest (2-3 paragraphs) that:
1. Summarizes the overall market sentiment based on news analysis
2. Highlights key news impacts on recommended stocks
3. Provides brief outlook for the week ahead

Keep it professional, factual, and focused on Vietnamese market conditions."""


def extract_news_scores(news_items: list[dict]) -> dict:
    """Extract structured sentiment scores from news items using llama-3.1-8b-instant.

    Args:
        news_items: List of news items with keys: symbol, title, summary, source

    Returns:
        Dict with extracted scores and metadata, or empty dict on failure
    """
    if not news_items:
        logger.info("No news items provided for extraction")
        return {"scores": {}, "overall_sentiment": "neutral", "generated": False}

    api_key = get_api_key()
    if not api_key:
        logger.info("GROQ_API_KEY not configured — skipping news extraction")
        return {"scores": {}, "overall_sentiment": "neutral", "generated": False}

    # Check cache first
    news_hash = _hash_news_items(news_items)
    cache = _load_cache()

    if news_hash in cache:
        logger.info(f"📦 News cache hit (hash={news_hash}) — skipping API call")
        result = cache[news_hash]
        result["cache_hit"] = True
        return result

    # Build prompt and call API
    prompt = _build_extraction_prompt(news_items)
    logger.info(f"Starting news extraction | model={_MODEL_EXTRACT} | items={len(news_items)}")

    cache_key = hashlib.sha256(prompt.encode()).hexdigest()[:16]
    if cache_key in _CACHE:
        logger.info(f"📦 Process cache hit (hash={cache_key})")
        return _CACHE[cache_key]

    result = _call_groq_with_retry(
        prompt=prompt,
        model=_MODEL_EXTRACT,
        api_key=api_key,
        max_tokens=1024,
        temperature=0.3
    )

    if result is None:
        logger.warning("News extraction failed — returning empty analysis")
        return {"scores": {}, "overall_sentiment": "neutral", "generated": False}

    # Validate and clean result
    scores = result.get("scores", {})
    overall_sentiment = result.get("overall_sentiment", "neutral")

    # Convert to expected format and add metadata
    final_result = {
        "scores": scores,
        "overall_sentiment": overall_sentiment,
        "generated": True,
        "cache_hit": False,
        "model": _MODEL_EXTRACT,
        "news_hash": news_hash
    }

    # Cache the result
    _CACHE[cache_key] = final_result
    cache[news_hash] = final_result
    _save_cache(cache)

    logger.info(f"News extraction complete: {len(scores)} symbols analyzed")
    return final_result


def compose_weekly_digest(plan: dict, news_scores: dict) -> str:
    """Compose weekly digest using llama-3.3-70b-versatile.

    Args:
        plan: Weekly plan dictionary
        news_scores: Output from extract_news_scores()

    Returns:
        Formatted weekly digest text, or fallback message on failure
    """
    api_key = get_api_key()
    if not api_key:
        logger.info("GROQ_API_KEY not configured — using fallback digest")
        return "Weekly market digest unavailable - Groq API key not configured."

    if not news_scores.get("generated", False):
        logger.info("No news scores available — using fallback digest")
        return "Weekly market digest unavailable - no news analysis data."

    # Build prompt and call API
    prompt = _build_digest_prompt(plan, news_scores)
    logger.info(f"Starting digest composition | model={_MODEL_DIGEST}")

    cache_key = hashlib.sha256(prompt.encode()).hexdigest()[:16]
    if cache_key in _CACHE:
        logger.info(f"📦 Process cache hit (hash={cache_key})")
        cached = _CACHE[cache_key]
        return cached.get("content", "Cached digest unavailable")

    result = _call_groq_with_retry(
        prompt=prompt,
        model=_MODEL_DIGEST,
        api_key=api_key,
        max_tokens=800,
        temperature=0.4
    )

    if result is None:
        logger.warning("Digest composition failed — returning fallback")
        return "Weekly market digest temporarily unavailable due to API issues."

    digest_content = result.get("content", "Digest content unavailable")

    # Cache the result
    _CACHE[cache_key] = result

    logger.info("Weekly digest composition complete")
    return digest_content