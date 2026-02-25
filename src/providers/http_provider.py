"""HTTP provider — fetches from public Simplize API (no auth)."""

from __future__ import annotations

import logging
import time as _time
from datetime import date, datetime, timedelta

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.models import OHLCV
from src.providers.base import PriceProvider

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 5
_CHUNK_DELAY_S = 1.5


class HttpProvider(PriceProvider):
    name = "http"

    def __init__(
        self,
        base_url: str = "https://api.simplize.vn/api/company/get-chart",
        timeout: int = 15,
        retries: int = 3,
    ):
        self.base_url = base_url
        self.timeout = timeout
        self.session = requests.Session()
        retry = Retry(
            total=retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))

    def get_daily_history(
        self, symbol: str, start: date, end: date
    ) -> list[OHLCV]:
        logger.info("http: fetching history for %s (%s to %s)", symbol, start, end)
        try:
            params = {
                "ticker": symbol,
                "from": self._to_timestamp(start),
                "to": self._to_timestamp(end),
            }
            resp = self.session.get(
                self.base_url,
                params=params,
                timeout=self.timeout,
                headers={"User-Agent": "IndicatorK/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
            return self._parse_response(data)
        except Exception as e:
            logger.warning("http: failed for %s: %s", symbol, e)
            return []

    def get_last_prices(self, symbols: list[str]) -> dict[str, float]:
        """Fetch latest prices in chunks with rate limiting."""
        result = {}
        end = date.today()
        start = end - timedelta(days=7)

        for i in range(0, len(symbols), _CHUNK_SIZE):
            chunk = symbols[i : i + _CHUNK_SIZE]
            for sym in chunk:
                try:
                    history = self.get_daily_history(sym, start, end)
                    if history:
                        result[sym] = history[-1].close
                except Exception as e:
                    logger.warning("http: failed to get price for %s: %s", sym, e)

            if i + _CHUNK_SIZE < len(symbols):
                _time.sleep(_CHUNK_DELAY_S)

        return result

    def _parse_response(self, data: dict | list) -> list[OHLCV]:
        """Parse Simplize API response into OHLCV list."""
        records = []

        # Handle different response shapes
        if isinstance(data, dict):
            data = data.get("data", data.get("chart", []))
        if not isinstance(data, list):
            return []

        for item in data:
            try:
                if isinstance(item, dict):
                    d = self._parse_date_field(item)
                    records.append(OHLCV(
                        date=d,
                        open=float(item.get("open", item.get("o", 0))),
                        high=float(item.get("high", item.get("h", 0))),
                        low=float(item.get("low", item.get("l", 0))),
                        close=float(item.get("close", item.get("c", 0))),
                        volume=float(item.get("volume", item.get("v", 0))),
                    ))
                elif isinstance(item, list) and len(item) >= 5:
                    # [timestamp, open, high, low, close, volume]
                    ts = item[0]
                    if isinstance(ts, (int, float)) and ts > 1e9:
                        d = datetime.utcfromtimestamp(ts / 1000 if ts > 1e12 else ts).date()
                    else:
                        d = datetime.strptime(str(ts)[:10], "%Y-%m-%d").date()
                    records.append(OHLCV(
                        date=d,
                        open=float(item[1]),
                        high=float(item[2]),
                        low=float(item[3]),
                        close=float(item[4]),
                        volume=float(item[5]) if len(item) > 5 else 0,
                    ))
            except Exception as e:
                logger.debug("http: skipping item: %s", e)

        records.sort(key=lambda x: x.date)
        return records

    def _parse_date_field(self, item: dict) -> date:
        for key in ("date", "time", "tradingDate", "t"):
            val = item.get(key)
            if val is None:
                continue
            if isinstance(val, (int, float)) and val > 1e9:
                return datetime.utcfromtimestamp(
                    val / 1000 if val > 1e12 else val
                ).date()
            if isinstance(val, str):
                return datetime.strptime(val[:10], "%Y-%m-%d").date()
        raise ValueError(f"No date field found in {list(item.keys())}")

    def _to_timestamp(self, d: date) -> int:
        return int(datetime.combine(d, datetime.min.time()).timestamp())
