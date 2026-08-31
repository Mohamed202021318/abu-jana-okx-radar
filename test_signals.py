"""
Quick test of the Signal Engine using public OKX data (no API keys needed)
"""

import ccxt
import time
from signal_engine import RadarSignalEngine


def main():
    print("Connecting to OKX public API...")
    exchange = ccxt.okx({
        "enableRateLimit": True,
    })

    symbol = "BTC/USDT"
    timeframe = "1m"
    limit = 100

    print(f"Fetching last {limit} candles for {symbol} ({timeframe})...")
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

    engine = RadarSignalEngine(
        min_bars_gap=3,
        vol_mult=1.0,
        sl_atr_mult=1.2,
    )

    engine.update_candles(ohlcv)

    print(f"Loaded {len(engine.candles)} candles")
    print("-" * 50)

    # Scan the whole history to see past signals
    signals_found = []
    for i in range(50, len(ohlcv)):  # start after enough history
        # Feed up to current bar
        engine.update_candles(ohlcv[: i + 1])
        sig = engine.detect_signal()
        if sig:
            signals_found.append(sig)
            ts = time.strftime("%Y-%m-%d %H:%M", time.gmtime(sig.timestamp / 1000))
            print(
                f"[{ts}] {sig.direction:4} @ {sig.price:.2f} | "
                f"SL: {sig.sl:.2f} | TP1: {sig.tp1:.2f} | TP2: {sig.tp2:.2f} | TP3: {sig.tp3:.2f}"
            )

    print("-" * 50)
    print(f"Total signals found in last ~{limit} candles: {len(signals_found)}")
    print("\nEngine is working. Ready for the full app.")


if __name__ == "__main__":
    main()
