"""Composite provider — fallback chain: primary -> secondary -> cache."""

from __future__ import annotations

import logging
from datetime import date, datetime

from src.models import OHLCV, ProviderHealth
from src.providers.base import PriceProvider
from src.providers.cache_provider import CacheProvider

logger = logging.getLogger(__name__)


class CompositeProvider(PriceProvider):
    name = "composite"

    def __init__(
        self,
        primary: PriceProvider,
        secondary: PriceProvider,
        cache: CacheProvider,
    ):
        self.primary = primary
        self.secondary = secondary
        self.cache = cache

        # Health tracking
        self._total_requests = 0
        self._total_errors = 0
        self._missing_count = 0
        self._requested_symbols = 0
        self._last_success_at: str | None = None

    def get_last_prices(self, symbols: list[str]) -> dict[str, float]:
        self._requested_symbols += len(symbols)
        self._total_requests += 1

        # Try primary
        result = self._try_provider(self.primary, "get_last_prices", symbols)
        if result is not None:
            self._update_cache_prices(result)
            missing = [s for s in symbols if s not in result]
            if missing:
                # Fill gaps from secondary
                secondary_result = self._try_provider(
                    self.secondary, "get_last_prices", missing
                )
                if secondary_result:
                    result.update(secondary_result)
                    self._update_cache_prices(secondary_result)
            self._track_missing(symbols, result)
            return result

        # Try secondary
        result = self._try_provider(self.secondary, "get_last_prices", symbols)
        if result is not None:
            self._update_cache_prices(result)
            self._track_missing(symbols, result)
            return result

        # Fallback to cache
        logger.warning("composite: both providers failed, falling back to cache")
        result = self.cache.get_last_prices(symbols)
        self._track_missing(symbols, result)
        return result

    def get_daily_history(
        self, symbol: str, start: date, end: date
    ) -> list[OHLCV]:
        self._total_requests += 1

        # Try primary
        result = self._try_provider_history(
            self.primary, symbol, start, end
        )
        if result:
            self._update_cache_history(symbol, result)
            return result

        # Try secondary
        result = self._try_provider_history(
            self.secondary, symbol, start, end
        )
        if result:
            self._update_cache_history(symbol, result)
            return result

        # Fallback to cache
        logger.warning(
            "composite: both providers failed for %s history, falling back to cache",
            symbol,
        )
        return self.cache.get_daily_history(symbol, start, end)

    def save_cache(self) -> None:
        """Persist the cache to disk."""
        self.cache.save()

    def get_health_stats(self) -> ProviderHealth:
        """Return health statistics for guardrails."""
        error_rate = (
            self._total_errors / self._total_requests
            if self._total_requests > 0
            else 0.0
        )
        missing_rate = (
            self._missing_count / self._requested_symbols
            if self._requested_symbols > 0
            else 0.0
        )
        return ProviderHealth(
            name=f"{self.primary.name}->{self.secondary.name}->cache",
            error_rate=error_rate,
            missing_rate=missing_rate,
            last_success_at=self._last_success_at,
            total_requests=self._total_requests,
            total_errors=self._total_errors,
        )

    def _try_provider(
        self, provider: PriceProvider, method: str, symbols: list[str]
    ) -> dict[str, float] | None:
        try:
            result = getattr(provider, method)(symbols)
            if result:
                self._last_success_at = datetime.utcnow().isoformat()
                logger.info(
                    "composite: %s returned %d/%d prices via %s",
                    provider.name, len(result), len(symbols), method,
                )
                return result
            self._total_errors += 1
            return None
        except Exception as e:
            self._total_errors += 1
            logger.warning("composite: %s.%s failed: %s", provider.name, method, e)
            return None

    def _try_provider_history(
        self,
        provider: PriceProvider,
        symbol: str,
        start: date,
        end: date,
    ) -> list[OHLCV]:
        try:
            result = provider.get_daily_history(symbol, start, end)
            if result:
                self._last_success_at = datetime.utcnow().isoformat()
                logger.info(
                    "composite: %s returned %d candles for %s",
                    provider.name, len(result), symbol,
                )
                return result
            self._total_errors += 1
            return []
        except Exception as e:
            self._total_errors += 1
            logger.warning(
                "composite: %s.get_daily_history failed for %s: %s",
                provider.name, symbol, e,
            )
            return []

    def _update_cache_prices(self, prices: dict[str, float]) -> None:
        for sym, price in prices.items():
            self.cache.update_symbol(sym, price)

    def _update_cache_history(self, symbol: str, history: list[OHLCV]) -> None:
        if history:
            self.cache.update_symbol(symbol, history[-1].close, history)

    def _track_missing(
        self, requested: list[str], received: dict[str, float]
    ) -> None:
        missing = len(requested) - len(received)
        if missing > 0:
            self._missing_count += missing
            logger.warning(
                "composite: %d/%d symbols missing prices",
                missing, len(requested),
            )
