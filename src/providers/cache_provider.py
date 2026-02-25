"""JSON file cache provider — read/write data/prices_cache.json."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path

from src.models import OHLCV
from src.providers.base import PriceProvider

logger = logging.getLogger(__name__)


class CacheProvider(PriceProvider):
    name = "cache"

    def __init__(self, cache_path: str = "data/prices_cache.json"):
        self.cache_path = Path(cache_path)
        self._data: dict | None = None

    def _load(self) -> dict:
        if self._data is not None:
            return self._data
        if self.cache_path.exists():
            try:
                with open(self.cache_path) as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("cache: failed to load %s: %s", self.cache_path, e)
                self._data = {}
        else:
            self._data = {}
        return self._data

    def save(self) -> None:
        """Persist the cache to disk."""
        data = self._load()
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def get_last_prices(self, symbols: list[str]) -> dict[str, float]:
        data = self._load()
        result = {}
        for sym in symbols:
            entry = data.get(sym)
            if entry and "last_price" in entry:
                result[sym] = float(entry["last_price"])
        return result

    def get_daily_history(
        self, symbol: str, start: date, end: date
    ) -> list[OHLCV]:
        data = self._load()
        entry = data.get(symbol, {})
        history = entry.get("history", {})
        records = []
        for date_str, ohlcv in history.items():
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d").date()
                if start <= d <= end:
                    records.append(OHLCV(
                        date=d,
                        open=float(ohlcv["open"]),
                        high=float(ohlcv["high"]),
                        low=float(ohlcv["low"]),
                        close=float(ohlcv["close"]),
                        volume=float(ohlcv.get("volume", 0)),
                    ))
            except (KeyError, ValueError) as e:
                logger.debug("cache: skipping entry for %s/%s: %s", symbol, date_str, e)
        records.sort(key=lambda x: x.date)
        return records

    def update_symbol(
        self,
        symbol: str,
        last_price: float,
        history: list[OHLCV] | None = None,
    ) -> None:
        """Update cache for a symbol (in-memory only; call save() to persist)."""
        data = self._load()
        if symbol not in data:
            data[symbol] = {}
        data[symbol]["last_price"] = last_price
        data[symbol]["updated_at"] = datetime.utcnow().isoformat()

        if history:
            if "history" not in data[symbol]:
                data[symbol]["history"] = {}
            for candle in history:
                data[symbol]["history"][candle.date.isoformat()] = {
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                }
