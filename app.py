"""
Abu Jana Radar Trader - Web App
FastAPI backend + simple web UI
"""

import os
import time
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import ccxt

from signal_engine import RadarSignalEngine, Signal
from position_manager import PositionManager


# ====================== CONFIG ======================
SYMBOL = "BTC/USDT"
TIMEFRAME = "1m"
POLL_INTERVAL = 15  # seconds (check more often than 1m for faster reverse detection)


# ====================== GLOBAL STATE ======================
class AppState:
    def __init__(self):
        self.engine = RadarSignalEngine(min_bars_gap=3, vol_mult=1.0, sl_atr_mult=1.2)
        self.pm = PositionManager()
        self.exchange: Optional[ccxt.okx] = None
        self.is_demo: bool = True
        self.api_configured: bool = False
        self.last_signal: Optional[Signal] = None
        self.last_price: float = 0.0
        self.status_message: str = "Waiting for API keys..."
        self.running: bool = False


state = AppState()


# ====================== MODELS ======================
class ApiKeys(BaseModel):
    api_key: str
    secret: str
    passphrase: str
    is_demo: bool = True


class OpenPositionRequest(BaseModel):
    direction: str  # "CALL" or "PUT"
    size: float     # quantity in BTC


class CloseRequest(BaseModel):
    reason: str = "CLOSED_MANUAL"


# ====================== LIFESPAN (background task) ======================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    state.running = True
    task = asyncio.create_task(background_loop())
    yield
    # Shutdown
    state.running = False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Abu Jana Radar Trader", lifespan=lifespan)


# ====================== BACKGROUND LOOP ======================
async def background_loop():
    """Poll OKX every few seconds, update signals, check for reverse exit"""
    while state.running:
        try:
            if state.api_configured and state.exchange:
                # Fetch recent candles
                ohlcv = state.exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=100)
                if ohlcv:
                    state.engine.update_candles(ohlcv)
                    state.last_price = float(ohlcv[-1][4])

                    # Detect new signal
                    new_sig = state.engine.detect_signal()
                    if new_sig:
                        state.last_signal = new_sig
                        state.status_message = f"New {new_sig.direction} signal @ {new_sig.price:.2f}"

                    # Check exit conditions if we have open position
                    if state.pm.has_open_position():
                        high = float(ohlcv[-1][2])
                        low = float(ohlcv[-1][3])
                        reason = state.pm.check_exit_conditions(
                            current_price=state.last_price,
                            high=high,
                            low=low,
                            new_signal=new_sig,
                        )
                        if reason:
                            # Close on exchange
                            await close_on_exchange(reason)
                            state.status_message = f"Position closed: {reason}"

        except Exception as e:
            state.status_message = f"Error: {str(e)[:80]}"
        
        await asyncio.sleep(POLL_INTERVAL)


async def close_on_exchange(reason: str):
    """Close the current position on OKX and update manager"""
    if not state.pm.has_open_position() or not state.exchange:
        return

    pos = state.pm.current_position
    try:
        # Market close
        side = "sell" if pos.direction == "CALL" else "buy"
        order = state.exchange.create_order(
            SYMBOL,
            "market",
            side,
            pos.size,
            params={"reduceOnly": True} if "reduceOnly" in str(state.exchange.has) else {}
        )
        exit_price = float(order.get("average") or order.get("price") or state.last_price)
        state.pm.close_position(exit_price, reason)
    except Exception as e:
        # Force close in manager even if exchange fails
        state.pm.close_position(state.last_price, reason + f" (exchange error: {e})")


# ====================== API ENDPOINTS ======================
@app.post("/api/configure")
async def configure_keys(keys: ApiKeys):
    """Set API keys and create exchange instance"""
    try:
        exchange = ccxt.okx({
            "apiKey": keys.api_key.strip(),
            "secret": keys.secret.strip(),
            "password": keys.passphrase.strip(),
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })

        # For Demo: user must create keys inside Demo Trading on OKX website
        # We just mark it
        state.is_demo = keys.is_demo
        state.exchange = exchange

        # Quick test
        balance = exchange.fetch_balance()
        usdt = balance.get("USDT", {}).get("free", 0)

        state.api_configured = True
        state.status_message = f"Connected ({'DEMO' if keys.is_demo else 'LIVE'}) | USDT free: {usdt:.2f}"

        return {
            "success": True,
            "is_demo": keys.is_demo,
            "usdt_balance": usdt,
            "message": state.status_message,
        }
    except Exception as e:
        state.api_configured = False
        raise HTTPException(status_code=400, detail=f"Failed to connect: {str(e)}")


@app.get("/api/status")
async def get_status():
    """Current status for the UI"""
    pos_status = state.pm.get_status()
    return {
        "api_configured": state.api_configured,
        "is_demo": state.is_demo,
        "status_message": state.status_message,
        "last_price": state.last_price,
        "last_signal": {
            "direction": state.last_signal.direction if state.last_signal else None,
            "price": state.last_signal.price if state.last_signal else None,
            "sl": state.last_signal.sl if state.last_signal else None,
            "tp1": state.last_signal.tp1 if state.last_signal else None,
            "tp2": state.last_signal.tp2 if state.last_signal else None,
            "tp3": state.last_signal.tp3 if state.last_signal else None,
            "time": datetime.utcfromtimestamp(state.last_signal.timestamp / 1000).isoformat() if state.last_signal else None,
        } if state.last_signal else None,
        "position": pos_status,
        "history_count": len(state.pm.history),
    }


@app.post("/api/open")
async def open_position(req: OpenPositionRequest):
    """Manual open CALL or PUT"""
    if not state.api_configured or not state.exchange:
        raise HTTPException(status_code=400, detail="Configure API keys first")

    if state.pm.has_open_position():
        raise HTTPException(status_code=400, detail="Already have an open position")

    direction = req.direction.upper()
    if direction not in ("CALL", "PUT"):
        raise HTTPException(status_code=400, detail="direction must be CALL or PUT")

    if req.size <= 0:
        raise HTTPException(status_code=400, detail="size must be > 0")

    # Use last signal levels if available and matching direction, else calculate fresh
    if state.last_signal and state.last_signal.direction == direction:
        sig = state.last_signal
    else:
        # Force a fresh calculation
        ohlcv = state.exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=100)
        state.engine.update_candles(ohlcv)
        sig = state.engine.detect_signal()
        if not sig or sig.direction != direction:
            # Create levels based on current price + ATR
            atr = state.engine._atr(14) or (state.last_price * 0.005)
            entry = state.last_price or float(ohlcv[-1][4])
            if direction == "CALL":
                sl = entry - (atr * 1.2)
                risk = entry - sl
                tp1, tp2, tp3 = entry + risk, entry + risk * 2, entry + risk * 3
            else:
                sl = entry + (atr * 1.2)
                risk = sl - entry
                tp1, tp2, tp3 = entry - risk, entry - risk * 2, entry - risk * 3
            from signal_engine import Signal
            sig = Signal(direction=direction, timestamp=int(time.time()*1000),
                         price=entry, atr=atr, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3, bar_index=0)

    # Place market order
    try:
        side = "buy" if direction == "CALL" else "sell"
        order = state.exchange.create_order(
            SYMBOL,
            "market",
            side,
            req.size,
        )
        fill_price = float(order.get("average") or order.get("price") or sig.price)

        pos = state.pm.open_position(
            direction=direction,
            entry_price=fill_price,
            size=req.size,
            sl=sig.sl,
            tp1=sig.tp1,
            tp2=sig.tp2,
            tp3=sig.tp3,
            signal_bar=sig.bar_index,
        )
        state.status_message = f"Opened {direction} {req.size} @ {fill_price:.2f}"
        return {
            "success": True,
            "position": state.pm.get_status(),
            "order_id": order.get("id"),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Order failed: {str(e)}")


@app.post("/api/close")
async def close_manual(req: CloseRequest = CloseRequest()):
    """Manual close"""
    if not state.pm.has_open_position():
        raise HTTPException(status_code=400, detail="No open position")

    await close_on_exchange(req.reason)
    return {"success": True, "message": "Position closed", "history": len(state.pm.history)}


@app.get("/api/balance")
async def get_balance():
    if not state.exchange:
        raise HTTPException(status_code=400, detail="Not connected")
    bal = state.exchange.fetch_balance()
    return {
        "USDT": bal.get("USDT", {}),
        "BTC": bal.get("BTC", {}),
    }


# ====================== FRONTEND ======================
@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_PAGE


HTML_PAGE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Abu Jana Radar Trader</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Segoe UI', Tahoma, sans-serif;
            background: #0e1621;
            color: #e0e0e0;
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 480px; margin: 0 auto; }
        h1 { text-align: center; color: #f0a500; margin-bottom: 8px; font-size: 1.5rem; }
        .subtitle { text-align: center; color: #888; margin-bottom: 24px; font-size: 0.9rem; }
        .card {
            background: #1a2332;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 16px;
            border: 1px solid #2a3544;
        }
        .label { color: #aaa; font-size: 0.85rem; margin-bottom: 4px; }
        .value { font-size: 1.2rem; font-weight: 600; }
        .green { color: #00c853; }
        .red { color: #ff5252; }
        .yellow { color: #ffd600; }
        .orange { color: #f0a500; }
        input, select {
            width: 100%;
            padding: 12px;
            margin: 6px 0 12px;
            border: 1px solid #333;
            border-radius: 8px;
            background: #0e1621;
            color: #fff;
            font-size: 1rem;
        }
        button {
            width: 100%;
            padding: 14px;
            border: none;
            border-radius: 8px;
            font-size: 1.1rem;
            font-weight: 700;
            cursor: pointer;
            margin: 6px 0;
            transition: opacity 0.2s;
        }
        button:active { opacity: 0.8; }
        .btn-call { background: #00c853; color: #000; }
        .btn-put { background: #ff5252; color: #fff; }
        .btn-close { background: #ff9800; color: #000; }
        .btn-config { background: #2196f3; color: #fff; }
        .btn-secondary { background: #333; color: #fff; }
        .status-bar {
            text-align: center;
            padding: 10px;
            border-radius: 8px;
            background: #1a2332;
            margin-bottom: 16px;
            font-size: 0.95rem;
        }
        .row { display: flex; gap: 10px; }
        .row > * { flex: 1; }
        .hidden { display: none; }
        .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 700;
        }
        .badge-demo { background: #2196f3; }
        .badge-live { background: #ff5252; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Abu Jana Radar V13</h1>
        <div class="subtitle">OKX Trader • 1m</div>

        <div id="statusBar" class="status-bar">جاري التحميل...</div>

        <!-- CONFIG CARD -->
        <div id="configCard" class="card">
            <div class="label">إعدادات API</div>
            <input type="text" id="apiKey" placeholder="API Key">
            <input type="password" id="secret" placeholder="Secret Key">
            <input type="password" id="passphrase" placeholder="Passphrase">
            <select id="mode">
                <option value="true">Demo (تجريبي)</option>
                <option value="false">Live (حقيقي)</option>
            </select>
            <button class="btn-config" onclick="configure()">ربط الحساب</button>
            <p style="font-size:0.8rem;color:#888;margin-top:8px;">
                للـ Demo: اعمل API Key من داخل Demo Trading على موقع OKX
            </p>
        </div>

        <!-- MAIN CARD -->
        <div id="mainCard" class="card hidden">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                <span id="modeBadge" class="badge badge-demo">DEMO</span>
                <span id="priceDisplay" class="value">—</span>
            </div>

            <div class="label">آخر إشارة</div>
            <div id="signalInfo" class="value" style="margin-bottom:16px;">—</div>

            <div class="label">الصفقة الحالية</div>
            <div id="posInfo" style="margin-bottom:16px;font-size:0.95rem;">لا توجد صفقة مفتوحة</div>

            <div class="label">حجم الصفقة (BTC)</div>
            <input type="number" id="sizeInput" value="0.001" step="0.001" min="0.0001">

            <div class="row">
                <button class="btn-call" onclick="openPos('CALL')">CALL 🚀</button>
                <button class="btn-put" onclick="openPos('PUT')">PUT 🔻</button>
            </div>
            <button class="btn-close" onclick="closePos()">إغلاق الصفقة الآن</button>
            <button class="btn-secondary" onclick="refresh()">تحديث</button>
        </div>
    </div>

    <script>
        let configured = false;

        async function configure() {
            const body = {
                api_key: document.getElementById('apiKey').value,
                secret: document.getElementById('secret').value,
                passphrase: document.getElementById('passphrase').value,
                is_demo: document.getElementById('mode').value === 'true'
            };
            try {
                const res = await fetch('/api/configure', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(body)
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Error');
                configured = true;
                document.getElementById('configCard').classList.add('hidden');
                document.getElementById('mainCard').classList.remove('hidden');
                document.getElementById('modeBadge').textContent = data.is_demo ? 'DEMO' : 'LIVE';
                document.getElementById('modeBadge').className = 'badge ' + (data.is_demo ? 'badge-demo' : 'badge-live');
                alert('تم الربط بنجاح\\n' + data.message);
                refresh();
            } catch (e) {
                alert('فشل الربط: ' + e.message);
            }
        }

        async function refresh() {
            try {
                const res = await fetch('/api/status');
                const d = await res.json();
                document.getElementById('statusBar').textContent = d.status_message;
                document.getElementById('priceDisplay').textContent = d.last_price ? d.last_price.toFixed(2) : '—';

                if (d.last_signal && d.last_signal.direction) {
                    const s = d.last_signal;
                    document.getElementById('signalInfo').innerHTML =
                        `<span class="${s.direction==='CALL'?'green':'red'}">${s.direction}</span> @ ${s.price.toFixed(2)}<br>
                         <small>SL: ${s.sl.toFixed(2)} | TP1: ${s.tp1.toFixed(2)} | TP2: ${s.tp2.toFixed(2)}</small>`;
                } else {
                    document.getElementById('signalInfo').textContent = 'لا توجد إشارة حديثة';
                }

                if (d.position && d.position.has_position) {
                    const p = d.position;
                    document.getElementById('posInfo').innerHTML =
                        `<span class="${p.direction==='CALL'?'green':'red'}">${p.direction}</span> 
                         حجم: ${p.size} | دخول: ${p.entry_price.toFixed(2)}<br>
                         SL: ${p.sl.toFixed(2)}`;
                } else {
                    document.getElementById('posInfo').textContent = 'لا توجد صفقة مفتوحة';
                }
            } catch (e) {
                document.getElementById('statusBar').textContent = 'خطأ في التحديث';
            }
        }

        async function openPos(dir) {
            const size = parseFloat(document.getElementById('sizeInput').value);
            if (!size || size <= 0) return alert('أدخل حجم صحيح');
            if (!confirm(`تأكيد فتح ${dir} بحجم ${size} BTC ؟`)) return;
            try {
                const res = await fetch('/api/open', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({direction: dir, size: size})
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Error');
                alert('تم فتح الصفقة');
                refresh();
            } catch (e) {
                alert('فشل: ' + e.message);
            }
        }

        async function closePos() {
            if (!confirm('تأكيد إغلاق الصفقة الحالية؟')) return;
            try {
                const res = await fetch('/api/close', {method: 'POST'});
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Error');
                alert('تم الإغلاق');
                refresh();
            } catch (e) {
                alert('فشل: ' + e.message);
            }
        }

        // Auto refresh every 10s
        setInterval(() => { if (configured) refresh(); }, 10000);
    </script>
</body>
</html>
"""
