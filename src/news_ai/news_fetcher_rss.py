"""RSS-based news fetching for Vietnamese stocks.

Updated to use official RSS feeds from VnExpress and VietNamNet
instead of web scraping to avoid 406 errors and bot detection.
"""

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, Dict, List

import requests

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15.0


def fetch_vnexpress_rss(days_back: int = 7) -> List[Dict[str, Any]]:
    """Fetch news from VnExpress RSS feeds.

    RSS URLs:
    - https://vnexpress.net/rss/kinh-doanh.rss (Business)
    - https://vnexpress.net/rss/chung-khoan.rss (Stock market)
    """
    articles = []

    rss_urls = [
        "https://vnexpress.net/rss/chung-khoan.rss",  # Stock market (priority)
        "https://vnexpress.net/rss/kinh-doanh.rss",  # Business
    ]

    cutoff_date = datetime.now() - timedelta(days=days_back)

    for rss_url in rss_urls:
        try:
            response = requests.get(rss_url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()

            # Parse RSS XML
            root = ET.fromstring(response.content)

            # RSS 2.0 format: <rss><channel><item>
            for item in root.findall(".//item")[:30]:  # Limit to 30 items per feed
                title_elem = item.find("title")
                link_elem = item.find("link")
                desc_elem = item.find("description")
                pubdate_elem = item.find("pubDate")

                if title_elem is None or link_elem is None:
                    continue

                title = title_elem.text or ""
                article_url = link_elem.text or ""
                description = desc_elem.text if desc_elem is not None else ""

                # Parse pubDate (format: "Mon, 03 Mar 2026 10:00:00 +0700")
                published_at = datetime.now().isoformat()
                if pubdate_elem is not None and pubdate_elem.text:
                    try:
                        from email.utils import parsedate_to_datetime
                        pub_dt = parsedate_to_datetime(pubdate_elem.text)

                        # Filter by date
                        if pub_dt < cutoff_date:
                            continue

                        published_at = pub_dt.isoformat()
                    except:
                        pass

                # Clean description (RSS often includes HTML tags)
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


def fetch_vietstock_rss(days_back: int = 7) -> List[Dict[str, Any]]:
    """Fetch news from VietStock RSS feed.

    RSS URL: https://vietstock.vn/rss
    """
    articles = []

    rss_url = "https://vietstock.vn/rss"  # Stock market news
    cutoff_date = datetime.now() - timedelta(days=days_back)

    try:
        response = requests.get(rss_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        # Parse RSS XML
        root = ET.fromstring(response.content)

        # RSS 2.0 format
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

            # Parse pubDate
            published_at = datetime.now().isoformat()
            if pubdate_elem is not None and pubdate_elem.text:
                try:
                    from email.utils import parsedate_to_datetime
                    pub_dt = parsedate_to_datetime(pubdate_elem.text)

                    # Filter by date
                    if pub_dt < cutoff_date:
                        continue

                    published_at = pub_dt.isoformat()
                except:
                    pass

            # Clean description
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


def fetch_vietnamnet_rss(days_back: int = 7) -> List[Dict[str, Any]]:
    """Fetch news from VietNamNet RSS feed.

    RSS URL: https://vnn.vietnamnet.vn/rss/kinh-te.rss
    """
    articles = []

    rss_url = "https://vnn.vietnamnet.vn/rss/kinh-te.rss"  # Economy/Business
    cutoff_date = datetime.now() - timedelta(days=days_back)

    try:
        response = requests.get(rss_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        # Parse RSS XML
        root = ET.fromstring(response.content)

        # RSS 2.0 format
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

            # Parse pubDate
            published_at = datetime.now().isoformat()
            if pubdate_elem is not None and pubdate_elem.text:
                try:
                    from email.utils import parsedate_to_datetime
                    pub_dt = parsedate_to_datetime(pubdate_elem.text)

                    # Filter by date
                    if pub_dt < cutoff_date:
                        continue

                    published_at = pub_dt.isoformat()
                except:
                    pass

            # Clean description
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


if __name__ == "__main__":
    # Quick test
    print("Testing VnExpress RSS...")
    vne_articles = fetch_vnexpress_rss(days_back=7)
    print(f"Got {len(vne_articles)} articles from VnExpress")
    if vne_articles:
        print(f"Sample: {vne_articles[0]['title']}")

    print("\nTesting VietStock RSS...")
    vs_articles = fetch_vietstock_rss(days_back=7)
    print(f"Got {len(vs_articles)} articles from VietStock")
    if vs_articles:
        print(f"Sample: {vs_articles[0]['title']}")

    print("\nTesting VietNamNet RSS...")
    vnn_articles = fetch_vietnamnet_rss(days_back=7)
    print(f"Got {len(vnn_articles)} articles from VietNamNet")
    if vnn_articles:
        print(f"Sample: {vnn_articles[0]['title']}")

    print(f"\n✅ Total: {len(vne_articles) + len(vs_articles) + len(vnn_articles)} articles")
