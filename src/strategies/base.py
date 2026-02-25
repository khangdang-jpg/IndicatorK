"""Strategy abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.models import PortfolioState, WeeklyPlan


class Strategy(ABC):
    """Interface for all trading strategies."""

    @property
    @abstractmethod
    def id(self) -> str: ...

    @property
    @abstractmethod
    def version(self) -> str: ...

    @abstractmethod
    def generate_weekly_plan(
        self,
        market_data: dict,
        portfolio_state: PortfolioState,
        config: dict,
    ) -> WeeklyPlan:
        """Generate a weekly trading plan.

        Args:
            market_data: {symbol: list[OHLCV]} daily candles
            portfolio_state: current portfolio state from engine
            config: risk params from risk.yml
        """
        ...
