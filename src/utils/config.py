"""YAML config loader and provider/strategy factory."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve(path: str) -> Path:
    """Resolve a path relative to project root."""
    p = Path(path)
    if p.is_absolute():
        return p
    return _PROJECT_ROOT / p


def load_yaml(path: str) -> dict:
    """Load a YAML config file safely."""
    resolved = _resolve(path)
    with open(resolved) as f:
        return yaml.safe_load(f) or {}


def get_risk_config(config_path: str = "config/risk.yml") -> dict:
    """Load risk configuration."""
    return load_yaml(config_path)


def get_provider(config_path: str = "config/providers.yml"):
    """Instantiate the composite provider from config.

    Returns a CompositeProvider with primary -> secondary -> cache fallback.
    """
    from src.providers.cache_provider import CacheProvider
    from src.providers.composite_provider import CompositeProvider
    from src.providers.http_provider import HttpProvider
    from src.providers.vnstock_provider import VnstockProvider

    cfg = load_yaml(config_path)
    primary_name = cfg.get("primary", "vnstock")
    secondary_name = cfg.get("secondary", "http")
    cache_path = str(_resolve(cfg.get("cache_path", "data/prices_cache.json")))

    provider_map = {
        "vnstock": lambda: VnstockProvider(
            source=cfg.get("vnstock", {}).get("source", "VCI"),
            timeout=cfg.get("vnstock", {}).get("timeout", 30),
        ),
        "http": lambda: HttpProvider(
            base_url=cfg.get("http", {}).get("base_url", ""),
            timeout=cfg.get("http", {}).get("timeout", 15),
            retries=cfg.get("http", {}).get("retries", 3),
        ),
        "cache": lambda: CacheProvider(cache_path=cache_path),
    }

    primary = _build_provider(primary_name, provider_map)
    secondary = _build_provider(secondary_name, provider_map)
    cache = CacheProvider(cache_path=cache_path)

    return CompositeProvider(primary=primary, secondary=secondary, cache=cache)


def _build_provider(name: str, provider_map: dict):
    """Build a single provider by name."""
    factory = provider_map.get(name)
    if factory is None:
        raise ValueError(
            f"Unknown provider '{name}'. Available: {list(provider_map.keys())}"
        )
    try:
        return factory()
    except Exception as e:
        logger.warning("Failed to init provider '%s': %s", name, e)
        raise


def get_strategy(config_path: str = "config/strategy.yml"):
    """Instantiate the active strategy from config."""
    from src.strategies.rebalance_50_50 import Rebalance5050Strategy
    from src.strategies.trend_momentum_atr import TrendMomentumATRStrategy

    cfg = load_yaml(config_path)
    active = cfg.get("active", "trend_momentum_atr")
    params = cfg.get(active, {})

    strategy_map = {
        "trend_momentum_atr": lambda: TrendMomentumATRStrategy(params=params),
        "rebalance_50_50": lambda: Rebalance5050Strategy(params=params),
    }

    factory = strategy_map.get(active)
    if factory is None:
        raise ValueError(
            f"Unknown strategy '{active}'. Available: {list(strategy_map.keys())}"
        )
    return factory()


def load_watchlist(path: str = "data/watchlist.txt") -> list[str]:
    """Load symbol universe from watchlist file.

    Falls back to a small built-in sample if the file is empty.
    """
    DEFAULT_SYMBOLS = ["HPG", "VNM", "FPT", "MWG", "VCB"]  # TODO: expand as needed

    resolved = _resolve(path)
    symbols = []
    try:
        with open(resolved) as f:
            for line in f:
                s = line.strip().upper()
                if s and not s.startswith("#"):
                    symbols.append(s)
    except FileNotFoundError:
        logger.warning("Watchlist not found at %s, using defaults", resolved)

    if not symbols:
        logger.warning("Watchlist is empty, using default sample: %s", DEFAULT_SYMBOLS)
        symbols = DEFAULT_SYMBOLS

    return symbols
