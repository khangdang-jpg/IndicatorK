"""News fetching module for Vietnamese stock analysis.

Fetches recent news articles about Vietnamese stock symbols from multiple sources:
- Primary: NewsAPI.org (free tier)
- Fallback: RSS feeds from VnExpress, VietStock, VietNamNet (reliable, no blocking)
- Smart symbol matching using company/brand keywords from symbol_aliases.yml
- Cache: Local storage with 24h TTL to avoid repeated fetches

Returns:
    List of news items with: id, title, source, snippet, published_at, url (optional), scope
"""

import hashlib
import json
import logging
import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests
import yaml

logger = logging.getLogger(__name__)

# Configuration
NEWS_CACHE_FILE = "data/news_cache.json"
SYMBOL_ALIASES_FILE = "data/symbol_aliases.yml"
CACHE_TTL_HOURS = 24
REQUEST_TIMEOUT = 15.0
MAX_RETRIES = 2


def _normalize_text(text: str) -> str:
    """Normalize Vietnamese text: lowercase + remove diacritics.

    Examples:
        "Thế Giới Di Động" -> "the gioi di dong"
        "Hòa Phát Group" -> "hoa phat group"
    """
    if not text:
        return ""

    # Convert to lowercase
    text = text.lower()

    # Remove Vietnamese diacritics using Unicode normalization
    # NFD decomposes characters into base + combining marks
    nfd = unicodedata.normalize('NFD', text)

    # Keep only base characters (remove combining marks)
    without_diacritics = ''.join(
        char for char in nfd
        if unicodedata.category(char) != 'Mn'  # Mn = Nonspacing Mark
    )

    return without_diacritics


def _load_symbol_aliases() -> Dict[str, List[str]]:
    """Load symbol-to-keyword mappings from YAML file.

    Returns dict like:
        {"STB": ["sacombank", "sai gon thuong tin", ...],
         "MWG": ["mobile world", "the gioi di dong", ...]}
    """
    try:
        with open(SYMBOL_ALIASES_FILE, 'r', encoding='utf-8') as f:
            aliases = yaml.safe_load(f)

        # Remove market keywords (starts with _)
        symbol_aliases = {
            k: [_normalize_text(kw) for kw in v]
            for k, v in aliases.items()
            if not k.startswith('_')
        }

        logger.info(f"Loaded aliases for {len(symbol_aliases)} symbols")
        return symbol_aliases

    except Exception as e:
        logger.warning(f"Failed to load symbol aliases: {e}")
        return {}


def _match_news_to_symbols(
    articles: List[Dict[str, Any]],
    symbols: List[str],
    symbol_aliases: Dict[str, List[str]]
) -> Dict[str, List[Dict[str, Any]]]:
    """Match news articles to specific symbols using keyword matching.

    For each symbol:
    - Match up to 5 articles that contain symbol keywords
    - If <2 matches, add 3 most recent market-wide articles as fallback
    - Add "scope" field: "symbol" or "market"

    Returns:
        Dict mapping symbol -> list of matched news items
    """
    # Normalize all article texts once
    normalized_articles = []
    for article in articles:
        title = article.get('title', '')
        snippet = article.get('snippet', '')
        combined_text = _normalize_text(f"{title} {snippet}")

        normalized_articles.append({
            'article': article,
            'normalized_text': combined_text,
            'published_at': article.get('published_at', '')
        })

    # Sort by publication date (most recent first)
    normalized_articles.sort(key=lambda x: x['published_at'], reverse=True)

    # Match articles to each symbol
    symbol_news = {}

    for symbol in symbols:
        keywords = symbol_aliases.get(symbol, [])
        if not keywords:
            logger.debug(f"No keywords for symbol {symbol}")
            continue

        # Find matching articles
        matched = []
        for item in normalized_articles:
            # Check if any keyword appears in the article
            if any(kw in item['normalized_text'] for kw in keywords):
                article_copy = item['article'].copy()
                article_copy['scope'] = 'symbol'
                matched.append(article_copy)

                if len(matched) >= 5:  # Max 5 per symbol
                    break

        logger.info(f"Symbol {symbol}: {len(matched)} matched articles")

        # Fallback: if <2 matches, add market-wide news
        if len(matched) < 2:
            market_articles_needed = 3
            added = 0

            for item in normalized_articles[:15]:  # Check top 15 most recent
                article_copy = item['article'].copy()
                article_id = article_copy.get('id', '')

                # Skip if already in matched
                if any(a.get('id') == article_id for a in matched):
                    continue

                # Add as market-wide fallback
                article_copy['scope'] = 'market'
                matched.append(article_copy)
                added += 1

                if added >= market_articles_needed:
                    break

            logger.info(f"Symbol {symbol}: added {added} market fallback articles")

        symbol_news[symbol] = matched

    return symbol_news

# Vietnamese stock symbols (common ones)
VIETNAMESE_SYMBOLS = {
    "STB", "VPB", "MWG", "VHM", "VIC", "VJC", "FPT", "VNM", "CTG", "BID",
    "BAC", "EIB", "VCB", "TCB", "HDB", "ACB", "ABBank", "SBV", "VRE", "DHG",
}


class NewsItem:
    """Data class for a news item."""

    def __init__(
        self,
        id: str,
        title: str,
        source: str,
        snippet: str,
        published_at: str,
        url: Optional[str] = None,
        symbol: Optional[str] = None,
    ):
        self.id = id
        self.title = title
        self.source = source
        self.snippet = snippet
        self.published_at = published_at
        self.url = url
        self.symbol = symbol

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "source": self.source,
            "snippet": self.snippet,
            "published_at": self.published_at,
            "url": self.url,
            "symbol": self.symbol,
        }


def _get_cache_dir() -> Path:
    """Get or create cache directory."""
    cache_dir = Path("data")
    cache_dir.mkdir(exist_ok=True, parents=True)
    return cache_dir


def _load_cache() -> Dict[str, Any]:
    """Load news cache from disk."""
    cache_path = _get_cache_dir() / "news_cache.json"
    if not cache_path.exists():
        return {"articles": [], "fetched_at": None}

    try:
        with open(cache_path, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load cache: {e}")
        return {"articles": [], "fetched_at": None}


def _save_cache(cache: Dict[str, Any]) -> None:
    """Save news cache to disk."""
    cache_path = _get_cache_dir() / "news_cache.json"
    try:
        with open(cache_path, "w") as f:
            json.dump(cache, f, indent=2)
        logger.info(f"Cached {len(cache.get('articles', []))} news items")
    except Exception as e:
        logger.warning(f"Failed to save cache: {e}")


def _is_cache_valid(cache: Dict[str, Any], max_age_hours: int = CACHE_TTL_HOURS) -> bool:
    """Check if cache is still valid (not older than max_age_hours)."""
    fetched_at = cache.get("fetched_at")
    if not fetched_at:
        return False

    try:
        fetched_time = datetime.fromisoformat(fetched_at)
        age = datetime.now() - fetched_time
        is_valid = age < timedelta(hours=max_age_hours)
        if is_valid:
            logger.info(f"Using cached news ({age.total_seconds():.0f}s old)")
        return is_valid
    except Exception as e:
        logger.warning(f"Failed to validate cache timestamp: {e}")
        return False


def _fetch_from_newsapi(symbols: List[str], days_back: int = 7) -> List[Dict[str, Any]]:
    """Fetch news from NewsAPI.org (free tier works without API key for common queries)."""
    api_key = os.environ.get("NEWS_API_KEY")
    if not api_key:
        logger.warning("NEWS_API_KEY not set, NewsAPI fetch will be limited")
        # Free tier has limited requests without key
        return []

    articles = []
    base_url = "https://newsapi.org/v2/everything"

    from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    # Fetch news for Vietnamese market
    queries = [
        "Vietnamese stocks market",
        "Thị trường chứng khoán Việt Nam",
        "Vietnam stock exchange",
    ]

    # Add symbol-specific queries
    for symbol in symbols[:5]:  # Limit to first 5 to avoid rate limiting
        queries.append(f'"{symbol}" OR "{symbol.lower()}"')

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    for query in queries:
        try:
            params = {
                "q": query,
                "from": from_date,
                "to": datetime.now().strftime("%Y-%m-%d"),
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 20,
            }

            response = requests.get(
                base_url,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 401:
                logger.warning("NewsAPI authentication failed - invalid/missing API key")
                return []
            elif response.status_code == 429:
                logger.warning("NewsAPI rate limit exceeded")
                break
            elif response.status_code != 200:
                logger.warning(f"NewsAPI error {response.status_code}: {response.text[:200]}")
                continue

            data = response.json()
            if data.get("status") == "ok":
                for article in data.get("articles", []):
                    articles.append({
                        "id": hashlib.md5(
                            article.get("url", "").encode()
                        ).hexdigest()[:16],
                        "title": article.get("title", ""),
                        "source": article.get("source", {}).get("name", "NewsAPI"),
                        "snippet": article.get("description", ""),
                        "published_at": article.get("publishedAt", ""),
                        "url": article.get("url"),
                    })
                logger.info(f"Fetched {len(articles)} articles from NewsAPI for query: {query[:30]}")
            else:
                logger.warning(f"NewsAPI error: {data.get('message', 'Unknown error')}")

        except requests.exceptions.Timeout:
            logger.warning("NewsAPI request timeout")
        except Exception as e:
            logger.warning(f"NewsAPI fetch failed: {e}")
            continue

    # Deduplicate by URL
    seen_urls = set()
    unique_articles = []
    for article in articles:
        url = article.get("url")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_articles.append(article)
        elif not url:
            unique_articles.append(article)

    logger.info(f"NewsAPI returned {len(unique_articles)} unique articles")
    return unique_articles


def _fetch_from_vnexpress(symbols: List[str], days_back: int = 7) -> List[Dict[str, Any]]:
    """Fetch news from VnExpress RSS feeds.

    Uses official RSS - reliable and doesn't get blocked.
    """
    articles = []
    rss_urls = [
        "https://vnexpress.net/rss/chung-khoan.rss",  # Stock market
        "https://vnexpress.net/rss/kinh-doanh.rss",  # Business
    ]
    cutoff_date = datetime.now() - timedelta(days=days_back)

    for rss_url in rss_urls:
        try:
            response = requests.get(rss_url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()

            root = ET.fromstring(response.content)

            for item in root.findall(".//item")[:30]:
                title_elem = item.find("title")
                link_elem = item.find("link")
                desc_elem = item.find("description")
                pubdate_elem = item.find("pubDate")

                if title_elem is None or link_elem is None:
                    continue

                title = title_elem.text or ""
                article_url = link_elem.text or ""
                description = desc_elem.text if desc_elem is not None else ""

                published_at = datetime.now().isoformat()
                if pubdate_elem is not None and pubdate_elem.text:
                    try:
                        from email.utils import parsedate_to_datetime
                        pub_dt = parsedate_to_datetime(pubdate_elem.text)
                        if pub_dt < cutoff_date:
                            continue
                        published_at = pub_dt.isoformat()
                    except:
                        pass

                snippet = re.sub(r'<[^>]+>', '', description).strip()[:200]
                if not snippet:
                    snippet = "VnExpress business news"

                articles.append({
                    "id": hashlib.md5(article_url.encode()).hexdigest()[:16],
                    "title": title,
                    "source": "VnExpress",
                    "snippet": snippet,
                    "published_at": published_at,
                    "url": article_url,
                })

        except Exception as e:
            logger.debug(f"Failed to fetch RSS from {rss_url}: {e}")
            continue

    logger.info(f"Fetched {len(articles)} articles from VnExpress RSS")
    return articles


def _fetch_from_vietstock(symbols: List[str], days_back: int = 7) -> List[Dict[str, Any]]:
    """Fetch news from VietStock RSS feed."""
    articles = []
    rss_url = "https://vietstock.vn/rss"
    cutoff_date = datetime.now() - timedelta(days=days_back)

    try:
        response = requests.get(rss_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        root = ET.fromstring(response.content)

        for item in root.findall(".//item")[:30]:
            title_elem = item.find("title")
            link_elem = item.find("link")
            desc_elem = item.find("description")
            pubdate_elem = item.find("pubDate")

            if title_elem is None or link_elem is None:
                continue

            title = title_elem.text or ""
            article_url = link_elem.text or ""
            description = desc_elem.text if desc_elem is not None else ""

            published_at = datetime.now().isoformat()
            if pubdate_elem is not None and pubdate_elem.text:
                try:
                    from email.utils import parsedate_to_datetime
                    pub_dt = parsedate_to_datetime(pubdate_elem.text)
                    if pub_dt < cutoff_date:
                        continue
                    published_at = pub_dt.isoformat()
                except:
                    pass

            snippet = re.sub(r'<[^>]+>', '', description).strip()[:200]
            if not snippet:
                snippet = "VietStock market news"

            articles.append({
                "id": hashlib.md5(article_url.encode()).hexdigest()[:16],
                "title": title,
                "source": "VietStock",
                "snippet": snippet,
                "published_at": published_at,
                "url": article_url,
            })

        logger.info(f"Fetched {len(articles)} articles from VietStock RSS")
        return articles

    except Exception as e:
        logger.warning(f"VietStock RSS fetch failed: {e}")

    return []


def _fetch_from_vietnamnet(symbols: List[str], days_back: int = 7) -> List[Dict[str, Any]]:
    """Fetch news from VietNamNet RSS feed."""
    articles = []
    rss_url = "https://vnn.vietnamnet.vn/rss/kinh-te.rss"
    cutoff_date = datetime.now() - timedelta(days=days_back)

    try:
        response = requests.get(rss_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        root = ET.fromstring(response.content)

        for item in root.findall(".//item")[:30]:
            title_elem = item.find("title")
            link_elem = item.find("link")
            desc_elem = item.find("description")
            pubdate_elem = item.find("pubDate")

            if title_elem is None or link_elem is None:
                continue

            title = title_elem.text or ""
            article_url = link_elem.text or ""
            description = desc_elem.text if desc_elem is not None else ""

            published_at = datetime.now().isoformat()
            if pubdate_elem is not None and pubdate_elem.text:
                try:
                    from email.utils import parsedate_to_datetime
                    pub_dt = parsedate_to_datetime(pubdate_elem.text)
                    if pub_dt < cutoff_date:
                        continue
                    published_at = pub_dt.isoformat()
                except:
                    pass

            snippet = re.sub(r'<[^>]+>', '', description).strip()[:200]
            if not snippet:
                snippet = "VietNamNet business news"

            articles.append({
                "id": hashlib.md5(article_url.encode()).hexdigest()[:16],
                "title": title,
                "source": "VietNamNet",
                "snippet": snippet,
                "published_at": published_at,
                "url": article_url,
            })

        logger.info(f"Fetched {len(articles)} articles from VietNamNet RSS")
        return articles

    except Exception as e:
        logger.warning(f"VietNamNet RSS fetch failed: {e}")

    return []


def fetch_recent_news(
    symbols: Optional[List[str]] = None,
    days_back: int = 7,
    use_cache: bool = True,
) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch recent news about Vietnamese stock symbols with smart matching.

    Tries multiple sources in order:
    1. Cache (if valid and use_cache=True)
    2. NewsAPI.org (if NEWS_API_KEY is set)
    3. VnExpress RSS feeds (reliable, no blocking)
    4. VietStock RSS feed (stock market focus)
    5. VietNamNet RSS feed (business news)

    Then matches articles to symbols using company/brand keywords:
    - Up to 5 matched articles per symbol (scope="symbol")
    - If <2 matches, adds 3 market-wide articles as fallback (scope="market")

    Args:
        symbols: List of stock symbols to fetch news for.
                Defaults to common Vietnamese stocks.
        days_back: Number of days back to fetch news. Defaults to 7.
        use_cache: Whether to use cached news if available. Defaults to True.

    Returns:
        Dict mapping symbol -> list of news items with:
        id, title, source, snippet, published_at, url, scope (symbol|market)
        Returns empty dict if all sources fail.
    """
    if symbols is None:
        symbols = list(VIETNAMESE_SYMBOLS)

    logger.info(f"Fetching news for {len(symbols)} symbols, last {days_back} days")

    # Try cache first
    if use_cache:
        cache = _load_cache()
        if _is_cache_valid(cache):
            symbol_news = cache.get("symbol_news", {})
            if symbol_news:
                total_articles = sum(len(articles) for articles in symbol_news.values())
                logger.info(f"Returning cached news for {len(symbol_news)} symbols ({total_articles} articles)")
                return symbol_news

    articles = []

    # Try NewsAPI first
    logger.info("Attempting to fetch from NewsAPI.org...")
    newsapi_articles = _fetch_from_newsapi(symbols, days_back)
    articles.extend(newsapi_articles)

    if articles:
        logger.info(f"Successfully fetched {len(articles)} articles")
    else:
        # Fallback to web scraping
        logger.info("NewsAPI fetch unsuccessful, falling back to RSS feeds...")

        # Try VnExpress RSS (stock market + business)
        vnexpress_articles = _fetch_from_vnexpress(symbols, days_back)
        articles.extend(vnexpress_articles)

        # Try VietStock RSS (stock market focus)
        vietstock_articles = _fetch_from_vietstock(symbols, days_back)
        articles.extend(vietstock_articles)

        # Try VietNamNet RSS if we still need more
        if len(articles) < 5:
            logger.info("Trying VietNamNet RSS for more articles...")
            vietnamnet_articles = _fetch_from_vietnamnet(symbols, days_back)
            articles.extend(vietnamnet_articles)

    # Deduplicate articles by URL or ID
    seen = set()
    unique_articles = []
    for article in articles:
        url = article.get("url")
        article_id = article.get("id")

        key = url if url else article_id
        if key not in seen:
            seen.add(key)
            unique_articles.append(article)

    if not unique_articles:
        logger.warning("No news articles fetched from any source")
        # Return empty dict with generic market news for each symbol
        generic_article = {
            "id": hashlib.md5(datetime.now().isoformat().encode()).hexdigest()[:16],
            "title": f"Vietnamese stock market news ({datetime.now().strftime('%Y-%m-%d')})",
            "source": "Default",
            "snippet": "Vietnamese market sentiment updates and general market analysis",
            "published_at": datetime.now().isoformat(),
            "url": None,
            "scope": "market"
        }
        return {symbol: [generic_article] for symbol in symbols}

    logger.info(f"Fetched {len(unique_articles)} unique news articles total")

    # Load symbol aliases and match articles to symbols
    symbol_aliases = _load_symbol_aliases()
    if not symbol_aliases:
        logger.warning("No symbol aliases loaded, returning generic market news")
        # Fall back to giving all articles to all symbols as "market" news
        for article in unique_articles:
            article['scope'] = 'market'
        return {symbol: unique_articles[:5] for symbol in symbols}

    # Smart matching: match articles to symbols using keywords
    symbol_news = _match_news_to_symbols(unique_articles, symbols, symbol_aliases)

    # Save to cache (per-symbol news)
    cache = {
        "symbol_news": symbol_news,
        "fetched_at": datetime.now().isoformat(),
        "symbols": symbols,
        "days_back": days_back,
    }
    _save_cache(cache)

    total_matched = sum(len(articles) for articles in symbol_news.values())
    logger.info(f"Matched {total_matched} articles across {len(symbol_news)} symbols")

    return symbol_news


def clear_cache() -> None:
    """Clear the news cache."""
    cache_path = _get_cache_dir() / "news_cache.json"
    try:
        if cache_path.exists():
            cache_path.unlink()
            logger.info("News cache cleared")
    except Exception as e:
        logger.warning(f"Failed to clear cache: {e}")
