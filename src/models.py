"""Shared dataclasses used across all modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass
class OHLCV:
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class TradeRecord:
    timestamp_iso: str
    asset_class: str  # stock | bond | fund
    symbol: str
    side: str  # BUY | SELL | CASH
    qty: float
    price: float
    fee: float = 0.0
    note: str = ""


@dataclass
class Position:
    symbol: str
    asset_class: str
    qty: float
    avg_cost: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


@dataclass
class Recommendation:
    symbol: str
    asset_class: str
    action: str  # BUY | HOLD | REDUCE | SELL
    buy_zone_low: float
    buy_zone_high: float
    stop_loss: float
    take_profit: float
    position_target_pct: float
    rationale_bullets: list[str] = field(default_factory=list)
    # entry_type: "breakout" → high >= entry_price; "pullback" → low <= entry <= high
    entry_type: str = "pullback"
    # breakout_level: week T-1's weekly high used as the breakout reference (highs[-2])
    breakout_level: float = 0.0
    # entry_price: explicit fill price (breakout_level*(1+buffer) or zone midpoint)
    entry_price: float = 0.0
    # signal_week_end: date of weekly[-1] when the plan was generated (week T)
    signal_week_end: Optional[date] = None
    # earliest_entry_date: first allowed fill date (Monday of T+1 for breakout)
    earliest_entry_date: Optional[date] = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "asset_class": self.asset_class,
            "action": self.action,
            "buy_zone_low": round(self.buy_zone_low, 2),
            "buy_zone_high": round(self.buy_zone_high, 2),
            "stop_loss": round(self.stop_loss, 2),
            "take_profit": round(self.take_profit, 2),
            "position_target_pct": round(self.position_target_pct, 4),
            "rationale_bullets": self.rationale_bullets,
            "entry_type": self.entry_type,
            "breakout_level": round(self.breakout_level, 2),
            "entry_price": round(self.entry_price, 2),
            "signal_week_end": self.signal_week_end.isoformat() if self.signal_week_end else None,
            "earliest_entry_date": self.earliest_entry_date.isoformat() if self.earliest_entry_date else None,
        }


@dataclass
class WeeklyPlan:
    generated_at: str
    strategy_id: str
    strategy_version: str
    allocation_targets: dict[str, float]
    recommendations: list[Recommendation]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "allocation_targets": self.allocation_targets,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> WeeklyPlan:
        _rec_fields = {f.name for f in Recommendation.__dataclass_fields__.values()}
        _date_fields = {"signal_week_end", "earliest_entry_date"}
        recs = []
        for r in d.get("recommendations", []):
            kwargs = {k: v for k, v in r.items() if k in _rec_fields}
            for f in _date_fields:
                if f in kwargs and isinstance(kwargs[f], str):
                    kwargs[f] = date.fromisoformat(kwargs[f])
            recs.append(Recommendation(**kwargs))
        return cls(
            generated_at=d["generated_at"],
            strategy_id=d["strategy_id"],
            strategy_version=d["strategy_version"],
            allocation_targets=d.get("allocation_targets", {}),
            recommendations=recs,
            notes=d.get("notes", []),
        )


@dataclass
class Alert:
    symbol: str
    alert_type: str  # ENTERED_BUY_ZONE | STOP_LOSS_HIT | TAKE_PROFIT_HIT
    current_price: float
    threshold: float  # the level that was crossed
    message: str = ""


@dataclass
class ProviderHealth:
    name: str
    error_rate: float
    missing_rate: float
    last_success_at: Optional[str]
    total_requests: int = 0
    total_errors: int = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "error_rate": round(self.error_rate, 4),
            "missing_rate": round(self.missing_rate, 4),
            "last_success_at": self.last_success_at,
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
        }


@dataclass
class StrategyHealth:
    rolling_cagr: Optional[float]
    drawdown: Optional[float]
    turnover: Optional[float]
    weeks_tracked: int = 0

    def to_dict(self) -> dict:
        return {
            "rolling_cagr": round(self.rolling_cagr, 4) if self.rolling_cagr is not None else None,
            "drawdown": round(self.drawdown, 4) if self.drawdown is not None else None,
            "turnover": round(self.turnover, 4) if self.turnover is not None else None,
            "weeks_tracked": self.weeks_tracked,
        }


@dataclass
class GuardrailsReport:
    generated_at: str
    provider_health: ProviderHealth
    strategy_health: StrategyHealth
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "provider_health": self.provider_health.to_dict(),
            "strategy_health": self.strategy_health.to_dict(),
            "recommendations": self.recommendations,
        }

    @classmethod
    def from_dict(cls, d: dict) -> GuardrailsReport:
        ph = d.get("provider_health", {})
        sh = d.get("strategy_health", {})
        return cls(
            generated_at=d.get("generated_at", ""),
            provider_health=ProviderHealth(
                name=ph.get("name", "unknown"),
                error_rate=ph.get("error_rate", 0),
                missing_rate=ph.get("missing_rate", 0),
                last_success_at=ph.get("last_success_at"),
                total_requests=ph.get("total_requests", 0),
                total_errors=ph.get("total_errors", 0),
            ),
            strategy_health=StrategyHealth(
                rolling_cagr=sh.get("rolling_cagr"),
                drawdown=sh.get("drawdown"),
                turnover=sh.get("turnover"),
                weeks_tracked=sh.get("weeks_tracked", 0),
            ),
            recommendations=d.get("recommendations", []),
        )


@dataclass
class PortfolioState:
    positions: dict[str, Position]
    cash: float
    total_value: float
    allocation: dict[str, float]  # stock_pct, bond_fund_pct, cash_pct
    unrealized_pnl: float
    realized_pnl: float
