"""
Abu Jana Ultimate Radar Pro V13 - Signal Engine (Python port)
Timeframe: 1m
"""

import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Signal:
    direction: str          # "CALL" or "PUT"
    timestamp: int
    price: float
    atr: float
    sl: float
    tp1: float
    tp2: float
    tp3: float
    bar_index: int


class RadarSignalEngine:
    def __init__(
        self,
        min_bars_gap: int = 3,
        vol_mult: float = 1.0,
        sl_atr_mult: float = 1.2,
        volume_sma_period: int = 20,
        body_sma_period: int = 14,
        breakout_lookback: int = 5,
        atr_period: int = 14,
    ):
        self.min_bars_gap = min_bars_gap
        self.vol_mult = vol_mult
        self.sl_atr_mult = sl_atr_mult
        self.volume_sma_period = volume_sma_period
        self.body_sma_period = body_sma_period
        self.breakout_lookback = breakout_lookback
        self.atr_period = atr_period

        # State
        self.last_sig_bar: int = -999
        self.last_sig_type: int = 0   # 1 = CALL, -1 = PUT
        self.candles: List[Candle] = []

    def update_candles(self, ohlcv: List[List]) -> None:
        """
        Update internal candle list from ccxt-style OHLCV
        ohlcv item: [timestamp, open, high, low, close, volume]
        """
        self.candles = [
            Candle(
                timestamp=int(c[0]),
                open=float(c[1]),
                high=float(c[2]),
                low=float(c[3]),
                close=float(c[4]),
                volume=float(c[5]),
            )
            for c in ohlcv
        ]

    def _sma(self, values: List[float], period: int) -> Optional[float]:
        if len(values) < period:
            return None
        return sum(values[-period:]) / period

    def _atr(self, period: int) -> Optional[float]:
        if len(self.candles) < period + 1:
            return None

        trs = []
        for i in range(1, len(self.candles)):
            c = self.candles[i]
            prev = self.candles[i - 1]
            tr = max(
                c.high - c.low,
                abs(c.high - prev.close),
                abs(c.low - prev.close),
            )
            trs.append(tr)

        if len(trs) < period:
            return None
        return sum(trs[-period:]) / period

    def detect_signal(self) -> Optional[Signal]:
        """
        Run the exact logic from the Pine Script on the latest closed candle.
        Returns Signal if a new valid CALL or PUT appears, else None.
        """
        n = len(self.candles)
        if n < max(self.volume_sma_period, self.body_sma_period, self.breakout_lookback, self.atr_period) + 5:
            return None

        # We work on the last closed candle (index -1)
        # For crossover we need previous values
        idx = n - 1
        curr = self.candles[idx]

        # Volume filter
        volumes = [c.volume for c in self.candles]
        avg_vol = self._sma(volumes, self.volume_sma_period)
        if avg_vol is None:
            return None
        volume_ok = curr.volume >= (avg_vol * self.vol_mult)

        # Impulse (body size)
        bodies = [abs(c.close - c.open) for c in self.candles]
        avg_body = self._sma(bodies, self.body_sma_period)
        if avg_body is None:
            return None
        body_size = abs(curr.close - curr.open)
        is_impulse = body_size > (avg_body * 0.8)

        # Highest high / lowest low of previous 5 bars (excluding current)
        prev_highs = [c.high for c in self.candles[idx - self.breakout_lookback : idx]]
        prev_lows = [c.low for c in self.candles[idx - self.breakout_lookback : idx]]
        highest_prev = max(prev_highs) if prev_highs else curr.high
        lowest_prev = min(prev_lows) if prev_lows else curr.low

        # Breakout conditions (matching Pine)
        # ta.crossover(close, ta.highest(high, 5)[1]) → close crosses above previous highest
        # We approximate with: close > highest of previous 5
        bullish_breakout = (
            (curr.close > highest_prev or (curr.close > curr.open and is_impulse))
            and volume_ok
        )
        bearish_breakout = (
            (curr.close < lowest_prev or (curr.close < curr.open and is_impulse))
            and volume_ok
        )

        radar_call = bullish_breakout
        radar_put = bearish_breakout

        # Time filter + anti-consecutive same direction
        time_ok = (idx - self.last_sig_bar) >= self.min_bars_gap

        can_call = radar_call and time_ok and self.last_sig_type != 1
        can_put = radar_put and time_ok and self.last_sig_type != -1

        if not (can_call or can_put):
            return None

        # Calculate ATR and levels
        atr = self._atr(self.atr_period)
        if atr is None or atr <= 0:
            return None

        if can_call:
            direction = "CALL"
            entry = curr.close
            sl = curr.low - (atr * self.sl_atr_mult)
            risk = entry - sl
            if risk <= 0:
                return None
            tp1 = entry + risk * 1.0
            tp2 = entry + risk * 2.0
            tp3 = entry + risk * 3.0
            self.last_sig_bar = idx
            self.last_sig_type = 1

        else:  # can_put
            direction = "PUT"
            entry = curr.close
            sl = curr.high + (atr * self.sl_atr_mult)
            risk = sl - entry
            if risk <= 0:
                return None
            tp1 = entry - risk * 1.0
            tp2 = entry - risk * 2.0
            tp3 = entry - risk * 3.0
            self.last_sig_bar = idx
            self.last_sig_type = -1

        return Signal(
            direction=direction,
            timestamp=curr.timestamp,
            price=entry,
            atr=atr,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            bar_index=idx,
        )

    def get_latest_signal_direction(self) -> Optional[str]:
        """Helper: returns last signal direction without generating new one"""
        if self.last_sig_type == 1:
            return "CALL"
        elif self.last_sig_type == -1:
            return "PUT"
        return None
