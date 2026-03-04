"""Two-stage Groq pipeline for news-based buy potential scoring."""

from __future__ import annotations

import json
import hashlib
import logging
import time
from pathlib import Path
from typing import Any, Dict, List

import requests

logger = logging.getLogger(__name__)

# Model configuration
MODEL_SCORING = "llama-3.1-8b-instant"
MODEL_VALIDATION = "llama-3.3-70b-versatile"
API_BASE = "https://api.groq.com/openai/v1"

# Rate limiting and retry
MAX_RETRIES = 3
RETRY_DELAY = 1.0
REQUEST_TIMEOUT = 30.0

# Cache configuration
CACHE_FILE = "data/news_cache.json"


def _get_api_key() -> str | None:
    """Get GROQ_API_KEY from environment."""
    import os
    return os.environ.get("GROQ_API_KEY")


def _is_available() -> bool:
    """Check if Groq API is configured."""
    return _get_api_key() is not None


def _cache_key(symbol: str, news_items: List[Dict]) -> str:
    """Generate cache key from symbol and news content."""
    news_hash = hashlib.md5(
        json.dumps([item.get("id", "") for item in news_items], sort_keys=True).encode()
    ).hexdigest()[:12]
    return f"{symbol}_{news_hash}"


def _load_cache() -> Dict[str, Any]:
    """Load news analysis cache."""
    cache_path = Path(CACHE_FILE)
    if not cache_path.exists():
        return {}

    try:
        return json.loads(cache_path.read_text())
    except Exception as e:
        logger.warning(f"Failed to load cache: {e}")
        return {}


def _save_cache(cache: Dict[str, Any]) -> None:
    """Save news analysis cache."""
    try:
        cache_path = Path(CACHE_FILE)
        cache_path.parent.mkdir(exist_ok=True, parents=True)
        cache_path.write_text(json.dumps(cache, indent=2))
    except Exception as e:
        logger.warning(f"Failed to save cache: {e}")


def _call_groq(prompt: str, model: str) -> Dict[str, Any] | None:
    """Make API call to Groq."""
    api_key = _get_api_key()
    if not api_key:
        logger.warning("GROQ_API_KEY not configured")
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2000,
        "temperature": 0.1
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                f"{API_BASE}/chat/completions",
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code == 429:
                logger.warning(f"Rate limit hit (attempt {attempt}/{MAX_RETRIES})")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY * attempt)
                    continue
                return None

            if response.status_code != 200:
                logger.error(f"Groq API error {response.status_code}: {response.text}")
                return None

            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()

            # Strip markdown code blocks if present
            if content.startswith("```json"):
                content = content[7:]
            elif content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            # Parse JSON
            try:
                result = json.loads(content)
                logger.info(f"✅ Groq API succeeded | model={model} (attempt {attempt})")
                return result
            except json.JSONDecodeError as e:
                logger.warning(f"Non-JSON response | model={model}: {e}")
                logger.warning(f"Response content: {content[:200]}")
                return None

        except requests.exceptions.Timeout:
            logger.warning(f"Timeout (attempt {attempt}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
                continue
        except Exception as e:
            logger.error(f"Groq API call failed: {e}")

        return None

    return None


def _stage_a_scoring(symbol: str, news_items: List[Dict]) -> Dict[str, Any] | None:
    """Stage A: Generate buy potential scores using news."""
    if not news_items:
        return {
            "symbol_scores": [{
                "symbol": symbol,
                "buy_potential_score": 50,
                "risk_score": 50,
                "confidence": 0.1,
                "horizon": "1-4w",
                "key_bull_points": [],
                "key_risks": [],
                "evidence": []
            }]
        }

    # Build news context
    news_text = "\n".join([
        f"ID: {item.get('id', f'news_{i}')} | {item.get('title', 'N/A')} | "
        f"{item.get('source', 'N/A')} | {item.get('snippet', 'N/A')[:200]}"
        for i, item in enumerate(news_items)
    ])

    prompt = f"""Vietnamese stock analyst. Analyze recent news for {symbol} and score buy potential.

NEWS ITEMS:
{news_text}

Score this symbol based ONLY on the provided news. Reference evidence IDs.

RULES:
- Every bull point/risk MUST reference a specific news ID from above
- If insufficient relevant news, set confidence low (0.1-0.3)
- No made-up facts or analysis beyond what's in the news
- Focus on 1-4 week trading horizon

IMPORTANT: Return ONLY raw JSON. Do NOT wrap in markdown code blocks.

{{
  "symbol_scores": [{{
    "symbol": "{symbol}",
    "buy_potential_score": 0-100,
    "risk_score": 0-100,
    "confidence": 0.0-1.0,
    "horizon": "1-4w",
    "key_bull_points": ["Point referencing evidence ID"],
    "key_risks": ["Risk referencing evidence ID"],
    "evidence": [{{"id": "news_1", "supports": "bull/risk/neutral"}}]
  }}]
}}"""

    return _call_groq(prompt, MODEL_SCORING)


def _stage_b_validation(stage_a_result: Dict[str, Any], news_items: List[Dict]) -> Dict[str, Any] | None:
    """Stage B: Validate and normalize the scoring results."""
    news_ids = {item.get("id", f"news_{i}") for i, item in enumerate(news_items)}

    prompt = f"""Validation expert. Review and fix this stock analysis JSON.

ORIGINAL ANALYSIS:
{json.dumps(stage_a_result, indent=2)}

AVAILABLE NEWS IDs: {list(news_ids)}

VALIDATION TASKS:
1. Verify JSON schema is correct
2. Remove any bull_points/risks that don't reference valid evidence IDs
3. Ensure all evidence IDs exist in the news list
4. Normalize scores to 0-100 range
5. Ensure confidence reflects evidence quality (low if few/weak sources)

IMPORTANT: Return ONLY the corrected raw JSON. Do NOT wrap in markdown blocks.

{{
  "symbol_scores": [{{
    "symbol": "...",
    "buy_potential_score": 0-100,
    "risk_score": 0-100,
    "confidence": 0.0-1.0,
    "horizon": "1-4w",
    "key_bull_points": [...],
    "key_risks": [...],
    "evidence": [{{"id": "...", "supports": "..."}}]
  }}]
}}"""

    return _call_groq(prompt, MODEL_VALIDATION)


def _score_symbol(symbol: str, news_items: List[Dict], cache: Dict[str, Any]) -> Dict[str, Any] | None:
    """Score a single symbol with caching."""
    cache_key = _cache_key(symbol, news_items)

    # Check cache first
    if cache_key in cache:
        logger.info(f"Using cached analysis for {symbol}")
        return cache[cache_key]

    logger.info(f"Analyzing {symbol} with {len(news_items)} news items")

    # Stage A: Scoring
    stage_a_result = _stage_a_scoring(symbol, news_items)
    if not stage_a_result:
        logger.warning(f"Stage A failed for {symbol}")
        return None

    # Stage B: Validation
    stage_b_result = _stage_b_validation(stage_a_result, news_items)
    if not stage_b_result:
        logger.warning(f"Stage B failed for {symbol}, using Stage A result")
        stage_b_result = stage_a_result

    # Cache the result
    cache[cache_key] = stage_b_result

    return stage_b_result


def score_buy_potential(weekly_plan_path: str, news_items: List[Dict]) -> Dict[str, Any]:
    """
    Score buy potential for symbols using news analysis.

    Args:
        weekly_plan_path: Path to weekly_plan.json
        news_items: List of news items with id, title, source, snippet

    Returns:
        Combined analysis results for all symbols
    """
    if not _is_available():
        logger.warning("Groq API not configured - returning empty scores")
        return {"symbol_scores": [], "status": "API_NOT_CONFIGURED"}

    # Load weekly plan to get symbols
    try:
        with open(weekly_plan_path) as f:
            plan = json.load(f)
        symbols = [rec["symbol"] for rec in plan.get("recommendations", [])]
    except Exception as e:
        logger.error(f"Failed to load weekly plan: {e}")
        return {"symbol_scores": [], "status": "PLAN_LOAD_ERROR"}

    if not symbols:
        logger.info("No symbols to analyze")
        return {"symbol_scores": [], "status": "NO_SYMBOLS"}

    # Group news by symbol (simple keyword matching for now)
    symbol_news = {}
    for symbol in symbols:
        symbol_news[symbol] = [
            item for item in news_items
            if symbol.lower() in (item.get("title", "") + " " + item.get("snippet", "")).lower()
        ]

    # Load cache
    cache = _load_cache()
    all_scores = []

    try:
        for symbol in symbols:
            news_for_symbol = symbol_news.get(symbol, [])

            result = _score_symbol(symbol, news_for_symbol, cache)
            if result and "symbol_scores" in result:
                all_scores.extend(result["symbol_scores"])

        # Save updated cache
        _save_cache(cache)

        return {
            "symbol_scores": all_scores,
            "status": "SUCCESS",
            "analyzed_symbols": len(all_scores),
            "total_news": len(news_items)
        }

    except Exception as e:
        logger.error(f"Buy potential scoring failed: {e}")
        return {"symbol_scores": [], "status": "ERROR", "error": str(e)}