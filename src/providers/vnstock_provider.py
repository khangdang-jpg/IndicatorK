"""vnstock library wrapper — Vietnamese stock data provider."""

from __future__ import annotations

import logging
import time as _time
from datetime import date, timedelta

from src.models import OHLCV
from src.providers.base import PriceProvider

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 5
_CHUNK_DELAY_S = 1.0


class VnstockProvider(PriceProvider):
    name = "vnstock"

    def __init__(self, source: str = "VCI", timeout: int = 30):
        self.source = source
        self.timeout = timeout
        self._vnstock = None
        self._init_library()

    def _init_library(self):
        try:
            from vnstock import Vnstock
            self._vnstock = Vnstock
        except ImportError:
            raise ImportError(
                "vnstock is not installed. Install it with:\n"
                "  pip install vnstock\n"
                "See https://pypi.org/project/vnstock/ for details."
            )

    def get_daily_history(
        self, symbol: str, start: date, end: date
    ) -> list[OHLCV]:
        logger.info("vnstock: fetching history for %s (%s to %s)", symbol, start, end)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                stock = self._vnstock().stock(symbol=symbol, source=self.source)
                df = stock.quote.history(
                    start=start.strftime("%Y-%m-%d"),
                    end=end.strftime("%Y-%m-%d"),
                )
                if df is None or df.empty:
                    logger.warning("vnstock: no data for %s", symbol)
                    return []
                return self._parse_dataframe(df)
            except Exception as e:
                logger.warning(
                    "vnstock: attempt %d/%d failed for %s: %s",
                    attempt + 1, max_retries, symbol, e,
                )
                if attempt < max_retries - 1:
                    _time.sleep(2 ** attempt)
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
                    logger.warning("vnstock: failed to get price for %s: %s", sym, e)

            if i + _CHUNK_SIZE < len(symbols):
                _time.sleep(_CHUNK_DELAY_S)

        return result

    def _parse_dataframe(self, df) -> list[OHLCV]:
        """Parse a vnstock DataFrame into OHLCV list."""
        records = []
        col_map = self._detect_columns(df)
        for _, row in df.iterrows():
            try:
                d = row[col_map["date"]]
                if hasattr(d, "date"):
                    d = d.date()
                elif isinstance(d, str):
                    from datetime import datetime
                    d = datetime.strptime(d[:10], "%Y-%m-%d").date()

                records.append(OHLCV(
                    date=d,
                    open=float(row[col_map["open"]]),
                    high=float(row[col_map["high"]]),
                    low=float(row[col_map["low"]]),
                    close=float(row[col_map["close"]]),
                    volume=float(row.get(col_map.get("volume", "volume"), 0)),
                ))
            except Exception as e:
                logger.debug("vnstock: skipping row: %s", e)
        records.sort(key=lambda x: x.date)
        return records

    def _detect_columns(self, df) -> dict[str, str]:
        """Detect column names from the DataFrame (vnstock can vary)."""
        cols = {c.lower(): c for c in df.columns}
        mapping = {}

        for key, candidates in [
            ("date", ["time", "date", "trading_date", "tradingdate"]),
            ("open", ["open"]),
            ("high", ["high"]),
            ("low", ["low"]),
            ("close", ["close"]),
            ("volume", ["volume", "vol"]),
        ]:
            for c in candidates:
                if c in cols:
                    mapping[key] = cols[c]
                    break
            else:
                if key != "volume":
                    raise ValueError(
                        f"Cannot find '{key}' column in DataFrame. "
                        f"Available: {list(df.columns)}"
                    )
                mapping[key] = "volume"

        return mapping
