"""Core backtest engine.

Responsibilities:
- Pure touch-logic functions (entry, SL, TP)
- Same-day tie-breaker resolution
- BacktestEngine: manages cash, open/closed trades, equity curve
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from src.models import OHLCV


# ---------------------------------------------------------------------------
# Trade dataclasses
# ---------------------------------------------------------------------------

@dataclass
class OpenTrade:
    symbol: str
    entry_date: date
    entry_price: float
    stop_loss: float
    take_profit: float
    qty: float
    cost_vnd: float  # entry_price * qty


@dataclass
class ClosedTrade:
    symbol: str
    entry_date: date
    entry_price: float
    exit_date: date
    exit_price: float
    reason: str          # "TP" | "SL"
    qty: float
    return_pct: float    # (exit - entry) / entry * 100
    pnl_vnd: float
    hold_days: int


# ---------------------------------------------------------------------------
# Pure touch logic (unit-testable, no side effects)
# ---------------------------------------------------------------------------

def entry_touched(candle: OHLCV, entry: float) -> bool:
    """Return True if the daily candle's range covers the entry price.

    Rule: low <= entry <= high  (OHLC touch rule — used for pullback entries).
    """
    return candle.low <= entry <= candle.high


def breakout_entry_touched(candle: OHLCV, entry: float) -> bool:
    """Return True when the intraday high reaches the breakout entry level.

    For breakout entries the stock can gap above the entry (low > entry) and
    still be a valid fill, so we only require high >= entry.
    """
    return candle.high >= entry


def close_confirm_touched(candle: OHLCV, entry: float) -> bool:
    """Return True when the daily close confirms the breakout above entry.

    Stricter than intraweek: requires the stock to *close* at or above the
    breakout level, filtering out intraday false spikes.
    """
    return candle.close >= entry


def sl_touched(candle: OHLCV, sl: float) -> bool:
    """Return True if the daily candle's low reaches the stop loss."""
    return candle.low <= sl


def tp_touched(candle: OHLCV, tp: float) -> bool:
    """Return True if the daily candle's high reaches the take profit."""
    return candle.high >= tp


def resolve_same_day(
    tie_breaker: str,
    sl: float,
    tp: float,
) -> tuple[str, float]:
    """Resolve a candle that touches both SL and TP on the same bar.

    Args:
        tie_breaker: "worst" → assume SL hit first; "best" → assume TP hit first.
        sl: stop-loss price.
        tp: take-profit price.

    Returns:
        (reason, exit_price) where reason is "SL" or "TP".
    """
    if tie_breaker == "best":
        return "TP", tp
    return "SL", sl  # default: worst


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

class BacktestEngine:
    """Portfolio simulator with configurable trade sizing.

    Primary (default) sizing: position_target_pct passed to try_enter()
        trade_value = current_equity * position_target_pct

    Legacy sizing (backward-compat): pass order_size to __init__
        trade_value = order_size (fixed VND)

    Usage:
        engine = BacktestEngine(initial_cash=10_000_000)
        if engine.try_enter(sym, entry, sl, tp, candle, position_target_pct=0.10):
            ...
        engine.process_day(candles_today, current_date)
        summary = engine.compute_summary(from_date, to_date)
    """

    def __init__(
        self,
        initial_cash: float,
        order_size: float | None = None,
        tie_breaker: str = "worst",
        exit_mode: str = "tpsl_only",
    ) -> None:
        if tie_breaker not in ("worst", "best"):
            raise ValueError(f"tie_breaker must be 'worst' or 'best', got {tie_breaker!r}")
        if exit_mode not in ("tpsl_only", "3action", "4action"):
            raise ValueError(f"exit_mode must be 'tpsl_only', '3action', or '4action', got {exit_mode!r}")
        self.initial_cash = initial_cash
        self.order_size = order_size  # None = use position_target_pct sizing
        self.tie_breaker = tie_breaker
        self.exit_mode = exit_mode
        self.cash = float(initial_cash)
        self.open_trades: list[OpenTrade] = []
        self.closed_trades: list[ClosedTrade] = []
        self.equity_curve: list[dict] = []
        self._last_price: dict[str, float] = {}  # latest close seen per symbol

    def _current_equity(self) -> float:
        """Current portfolio value: cash + open positions marked to last price."""
        open_val = sum(
            t.qty * self._last_price.get(t.symbol, t.entry_price)
            for t in self.open_trades
        )
        return self.cash + open_val

    # ------------------------------------------------------------------
    # Entry
    # ------------------------------------------------------------------

    def try_enter(
        self,
        symbol: str,
        entry: float,
        sl: float,
        tp: float,
        candle: OHLCV,
        position_target_pct: float | None = None,
        entry_type: str = "pullback",
        earliest_entry_date: Optional[date] = None,
    ) -> bool:
        """Attempt to open a position if the candle satisfies the entry condition.

        Entry condition (controlled by entry_type):
          "pullback"  (default): low <= entry <= high  (intraday range touch)
          "breakout":            high >= entry          (gap-up fills correctly;
                                                         weekly close-confirm was
                                                         already done by the strategy)

        earliest_entry_date: if set, any candle dated before this is rejected.
          Used to enforce T+1 entry for breakout signals (the signal/confirm week
          is week T; the earliest fill is Monday of week T+1).

        Sizing priority:
          1. position_target_pct > 0  → trade_value = current_equity * pct
          2. self.order_size set       → trade_value = order_size (legacy)
          3. neither                   → return False

        Deducts cost from cash on success.  Returns True if filled.
        No exit check is performed on the entry candle (same-day entry+exit
        is prevented by process_day skipping trades entered today).
        """
        self._last_price[symbol] = candle.close

        # T+1 enforcement: reject breakout candles before the earliest allowed fill date.
        # Pullback entries are never gated (earliest_entry_date is always None for them).
        if entry_type == "breakout" and earliest_entry_date is not None and candle.date < earliest_entry_date:
            return False

        triggered = (
            breakout_entry_touched(candle, entry)
            if entry_type == "breakout"
            else entry_touched(candle, entry)
        )
        if not triggered:
            return False

        if position_target_pct and position_target_pct > 0:
            trade_value = self._current_equity() * position_target_pct
        elif self.order_size:
            trade_value = self.order_size
        else:
            return False

        qty = math.floor(trade_value / entry)
        if qty <= 0:
            return False

        cost = qty * entry
        if cost > self.cash:
            return False

        self.cash -= cost
        self.open_trades.append(
            OpenTrade(
                symbol=symbol,
                entry_date=candle.date,
                entry_price=entry,
                stop_loss=sl,
                take_profit=tp,
                qty=qty,
                cost_vnd=cost,
            )
        )
        return True

    # ------------------------------------------------------------------
    # Manual exits (for REDUCE/SELL signals)
    # ------------------------------------------------------------------

    def force_exit_at_market(
        self,
        symbol: str,
        current_date: date,
        market_price: float,
        reason: str = "SELL",
    ) -> bool:
        """Force exit entire position at market price.

        Returns True if position was closed, False if no position found.
        """
        for i, trade in enumerate(self.open_trades):
            if trade.symbol == symbol:
                # Close the trade at market price
                proceeds = trade.qty * market_price
                self.cash += proceeds
                pnl = proceeds - trade.cost_vnd
                return_pct = (market_price - trade.entry_price) / trade.entry_price * 100
                hold_days = (current_date - trade.entry_date).days

                self.closed_trades.append(
                    ClosedTrade(
                        symbol=trade.symbol,
                        entry_date=trade.entry_date,
                        entry_price=trade.entry_price,
                        exit_date=current_date,
                        exit_price=market_price,
                        reason=reason,
                        qty=trade.qty,
                        return_pct=round(return_pct, 4),
                        pnl_vnd=round(pnl, 2),
                        hold_days=hold_days,
                    )
                )

                # Remove the trade from open positions
                self.open_trades.pop(i)
                return True
        return False

    def reduce_position(
        self,
        symbol: str,
        current_date: date,
        market_price: float,
        reduction_fraction: float = 0.5,
        reason: str = "REDUCE",
    ) -> bool:
        """Reduce position by specified fraction at market price.

        Args:
            reduction_fraction: Fraction to sell (0.5 = sell 50%, keep 50%)

        Returns True if position was reduced, False if no position found.
        """
        for trade in self.open_trades:
            if trade.symbol == symbol:
                # Calculate quantity to sell
                qty_to_sell = math.floor(trade.qty * reduction_fraction)
                if qty_to_sell <= 0:
                    return False

                # Execute the partial sale
                proceeds = qty_to_sell * market_price
                self.cash += proceeds

                # Calculate PnL on the sold portion
                cost_of_sold = (trade.cost_vnd / trade.qty) * qty_to_sell
                pnl = proceeds - cost_of_sold
                return_pct = (market_price - trade.entry_price) / trade.entry_price * 100
                hold_days = (current_date - trade.entry_date).days

                self.closed_trades.append(
                    ClosedTrade(
                        symbol=trade.symbol,
                        entry_date=trade.entry_date,
                        entry_price=trade.entry_price,
                        exit_date=current_date,
                        exit_price=market_price,
                        reason=reason,
                        qty=qty_to_sell,
                        return_pct=round(return_pct, 4),
                        pnl_vnd=round(pnl, 2),
                        hold_days=hold_days,
                    )
                )

                # Update the remaining position
                trade.qty -= qty_to_sell
                trade.cost_vnd -= cost_of_sold
                return True
        return False

    # ------------------------------------------------------------------
    # Daily processing (SL/TP check + equity curve snapshot)
    # ------------------------------------------------------------------

    def process_day(
        self,
        candles_by_symbol: dict[str, OHLCV],
        current_date: date,
    ) -> None:
        """Check SL/TP for all open trades and record today's equity curve.

        Trades entered on *current_date* are skipped (no same-day exit).

        In manual exit modes (3action, 4action), SL/TP checks are skipped -
        exits are handled by explicit REDUCE/SELL signals.
        """
        # Update last-known prices from today's candles
        for sym, candle in candles_by_symbol.items():
            self._last_price[sym] = candle.close

        # Only check automatic SL/TP in "tpsl_only" mode
        if self.exit_mode == "tpsl_only":
            still_open: list[OpenTrade] = []
            for trade in self.open_trades:
                # Never exit on the same day as entry
                if trade.entry_date >= current_date:
                    still_open.append(trade)
                    continue

                candle = candles_by_symbol.get(trade.symbol)
                if candle is None:
                    still_open.append(trade)
                    continue

                hit_sl = sl_touched(candle, trade.stop_loss)
                hit_tp = tp_touched(candle, trade.take_profit)

                if hit_sl and hit_tp:
                    reason, exit_price = resolve_same_day(
                        self.tie_breaker, trade.stop_loss, trade.take_profit
                    )
                elif hit_tp:
                    reason, exit_price = "TP", trade.take_profit
                elif hit_sl:
                    reason, exit_price = "SL", trade.stop_loss
                else:
                    still_open.append(trade)
                    continue

                # Close the trade
                proceeds = trade.qty * exit_price
                self.cash += proceeds
                pnl = proceeds - trade.cost_vnd
                return_pct = (exit_price - trade.entry_price) / trade.entry_price * 100
                hold_days = (current_date - trade.entry_date).days

                self.closed_trades.append(
                    ClosedTrade(
                        symbol=trade.symbol,
                        entry_date=trade.entry_date,
                        entry_price=trade.entry_price,
                        exit_date=current_date,
                        exit_price=exit_price,
                        reason=reason,
                        qty=trade.qty,
                        return_pct=round(return_pct, 4),
                        pnl_vnd=round(pnl, 2),
                        hold_days=hold_days,
                    )
                )

            self.open_trades = still_open

        # Equity curve snapshot (mark open positions to last known price)
        open_value = sum(
            t.qty * self._last_price.get(t.symbol, t.entry_price)
            for t in self.open_trades
        )
        self.equity_curve.append(
            {
                "date": current_date.isoformat(),
                "total_value": round(self.cash + open_value, 2),
                "cash": round(self.cash, 2),
                "open_positions_value": round(open_value, 2),
            }
        )

    # ------------------------------------------------------------------
    # Summary metrics
    # ------------------------------------------------------------------

    def compute_summary(self, from_date: date, to_date: date) -> dict:
        """Compute CAGR, max drawdown, win rate, avg hold days, profit factor."""
        total_days = max((to_date - from_date).days, 1)

        if self.equity_curve:
            final_value = self.equity_curve[-1]["total_value"]
        else:
            final_value = float(self.initial_cash)

        # CAGR
        if final_value > 0 and self.initial_cash > 0:
            cagr = (final_value / self.initial_cash) ** (365.0 / total_days) - 1.0
        else:
            cagr = -1.0

        # Max drawdown
        peak = float(self.initial_cash)
        max_dd = 0.0
        for point in self.equity_curve:
            v = point["total_value"]
            if v > peak:
                peak = v
            if peak > 0:
                dd = (peak - v) / peak
                if dd > max_dd:
                    max_dd = dd

        # Trade statistics
        num_trades = len(self.closed_trades)
        wins = [t for t in self.closed_trades if t.pnl_vnd > 0]
        losses = [t for t in self.closed_trades if t.pnl_vnd <= 0]

        win_rate = len(wins) / num_trades if num_trades > 0 else 0.0
        avg_hold = (
            sum(t.hold_days for t in self.closed_trades) / num_trades
            if num_trades > 0
            else 0.0
        )

        gross_profit = sum(t.pnl_vnd for t in wins)
        gross_loss = abs(sum(t.pnl_vnd for t in losses))
        if gross_loss > 0:
            profit_factor: Optional[float] = gross_profit / gross_loss
        elif gross_profit > 0:
            profit_factor = None  # effectively infinite
        else:
            profit_factor = 0.0

        # Average capital utilisation (fraction of equity invested on trading days)
        if self.equity_curve:
            invested_fracs = [
                p["open_positions_value"] / p["total_value"]
                for p in self.equity_curve
                if p["total_value"] > 0
            ]
            avg_invested_pct = (
                round(sum(invested_fracs) / len(invested_fracs), 4)
                if invested_fracs else 0.0
            )
        else:
            avg_invested_pct = 0.0

        return {
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "initial_cash": self.initial_cash,
            "final_value": round(final_value, 2),
            "cagr": round(cagr, 4),
            "max_drawdown": round(max_dd, 4),
            "win_rate": round(win_rate, 4),
            "avg_hold_days": round(avg_hold, 2),
            "num_trades": num_trades,
            "profit_factor": (
                round(profit_factor, 4) if profit_factor is not None else None
            ),
            "avg_invested_pct": avg_invested_pct,
        }
