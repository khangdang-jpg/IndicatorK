"""PriceProvider abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from src.models import OHLCV


class PriceProvider(ABC):
    """Interface for all price data providers."""

    name: str = "base"

    @abstractmethod
    def get_last_prices(self, symbols: list[str]) -> dict[str, float]:
        """Get the latest price for each symbol.

        Returns a dict mapping symbol -> last close price.
        Missing symbols are omitted from the result.
        """
        ...

    @abstractmethod
    def get_daily_history(
        self, symbol: str, start: date, end: date
    ) -> list[OHLCV]:
        """Get daily OHLCV history for a single symbol.

        Returns a list of OHLCV sorted by date ascending.
        """
        ...
