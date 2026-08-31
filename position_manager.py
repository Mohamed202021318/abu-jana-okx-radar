"""
Position Manager
- Manual entry (user decides size and direction)
- Automatic exit on opposite signal
- Protective ATR-based Stop Loss
"""

from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime
from signal_engine import Signal


@dataclass
class Position:
    direction: str              # "CALL" or "PUT"
    entry_price: float
    size: float                 # quantity (e.g. BTC amount)
    sl: float
    tp1: float
    tp2: float
    tp3: float
    entry_time: datetime
    entry_signal_bar: int
    status: str = "OPEN"        # OPEN, CLOSED_SL, CLOSED_REVERSE, CLOSED_MANUAL, CLOSED_TP
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    pnl: Optional[float] = None


class PositionManager:
    def __init__(self):
        self.current_position: Optional[Position] = None
        self.history: List[Position] = []

    def has_open_position(self) -> bool:
        return self.current_position is not None and self.current_position.status == "OPEN"

    def open_position(
        self,
        direction: str,
        entry_price: float,
        size: float,
        sl: float,
        tp1: float,
        tp2: float,
        tp3: float,
        signal_bar: int,
    ) -> Position:
        if self.has_open_position():
            raise ValueError("There is already an open position. Close it first.")

        pos = Position(
            direction=direction,
            entry_price=entry_price,
            size=size,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            entry_time=datetime.utcnow(),
            entry_signal_bar=signal_bar,
        )
        self.current_position = pos
        return pos

    def check_exit_conditions(
        self,
        current_price: float,
        high: float,
        low: float,
        new_signal: Optional[Signal],
    ) -> Optional[str]:
        """
        Check if we should close the position.
        Priority:
        1. Opposite signal (reverse) → CLOSE_REVERSE
        2. Hit SL → CLOSE_SL
        3. (Optional) Hit TPs can be handled later
        Returns reason string if should close, else None
        """
        if not self.has_open_position():
            return None

        pos = self.current_position

        # 1. Reverse signal (highest priority as requested by user)
        if new_signal is not None:
            if pos.direction == "CALL" and new_signal.direction == "PUT":
                return "CLOSED_REVERSE"
            if pos.direction == "PUT" and new_signal.direction == "CALL":
                return "CLOSED_REVERSE"

        # 2. Protective Stop Loss
        if pos.direction == "CALL":
            if low <= pos.sl:
                return "CLOSED_SL"
        else:  # PUT
            if high >= pos.sl:
                return "CLOSED_SL"

        return None

    def close_position(self, exit_price: float, reason: str) -> Position:
        if not self.has_open_position():
            raise ValueError("No open position to close")

        pos = self.current_position
        pos.exit_price = exit_price
        pos.exit_time = datetime.utcnow()
        pos.status = reason

        # Calculate PnL (simple, without fees)
        if pos.direction == "CALL":
            pos.pnl = (exit_price - pos.entry_price) * pos.size
        else:
            pos.pnl = (pos.entry_price - exit_price) * pos.size

        self.history.append(pos)
        self.current_position = None
        return pos

    def get_status(self) -> dict:
        if not self.has_open_position():
            return {
                "has_position": False,
                "direction": None,
                "entry_price": None,
                "size": None,
                "sl": None,
                "unrealized_pnl": None,
            }

        pos = self.current_position
        return {
            "has_position": True,
            "direction": pos.direction,
            "entry_price": pos.entry_price,
            "size": pos.size,
            "sl": pos.sl,
            "tp1": pos.tp1,
            "tp2": pos.tp2,
            "tp3": pos.tp3,
            "entry_time": pos.entry_time.isoformat(),
        }
