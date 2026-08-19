import os
import time
import hmac
import hashlib
import asyncio
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

load_dotenv()

app = FastAPI(
    title="Quantum Nexus Testnet Bridge",
    version="1.0.0",
)

BINANCE_BASE = os.getenv(
    "BINANCE_FUTURES_TESTNET_URL",
    os.getenv(
        "BINANCE_TESTNET_BASE_URL",
        "https://testnet.binancefuture.com"
    ),
).rstrip("/")

def env_first(*names):
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return ""

BINANCE_KEY = env_first(
    "BINANCE_API_KEY",
    "BINANCE_API_KEY_TESTNET",
    "BINANCE_FUTURES_API_KEY",
    "BINANCE_TESTNET_API_KEY",
)

BINANCE_SECRET = env_first(
    "BINANCE_API_SECRET",
    "BINANCE_SECRET_KEY",
    "BINANCE_API_SECRET_TESTNET",
    "BINANCE_FUTURES_API_SECRET",
    "BINANCE_TESTNET_SECRET",
)

ENGINE_URL = os.getenv(
    "ENGINE_URL",
    "http://127.0.0.1:8000"
).rstrip("/")

class Order(BaseModel):
    symbol: str = Field(default="BTCUSDT")
    side: str
    quantity: str
    order_type: str = "MARKET"
    position_side: str = "BOTH"
    reduce_only: bool = False

def signed_params(params):
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    query = urlencode(params)
    signature = hmac.new(
        BINANCE_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()
    params["signature"] = signature
    return params

async def binance(method, path, params=None):
    if not BINANCE_KEY or not BINANCE_SECRET:
        raise HTTPException(
            503,
            "Binance testnet API credentials not detected in .env"
        )

    params = params or {}
    signed = signed_params(params)

    headers = {
        "X-MBX-APIKEY": BINANCE_KEY
    }

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=5.0)
    ) as client:
        r = await client.request(
            method,
            BINANCE_BASE + path,
            params=signed,
            headers=headers,
        )

    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}

    if r.status_code >= 400:
        raise HTTPException(r.status_code, data)

    return data

@app.get("/")
async def root():
    return {
        "service": "quantum-nexus-testnet-bridge",
        "status": "online",
        "engine": ENGINE_URL,
        "exchange": "BINANCE_USDM_TESTNET",
    }

@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "testnet-bridge",
        "binance_credentials": bool(BINANCE_KEY and BINANCE_SECRET),
        "engine_url": ENGINE_URL,
    }

@app.get("/status")
async def status():
    result = {
        "bridge": "online",
        "binance_testnet": "configured"
        if BINANCE_KEY and BINANCE_SECRET
        else "missing_credentials",
        "engine": "unknown",
    }

    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{ENGINE_URL}/health")
            result["engine"] = r.json()
    except Exception as e:
        result["engine"] = {
            "online": False,
            "error": str(e)
        }

    return result

@app.get("/summary")
async def summary():
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.get(f"{ENGINE_URL}/summary")
        return r.json()

@app.get("/positions")
async def positions():
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.get(f"{ENGINE_URL}/positions")
        return r.json()

@app.get("/journal")
async def journal():
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.get(f"{ENGINE_URL}/journal")
        return r.json()

@app.get("/testnet/time")
async def testnet_time():
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{BINANCE_BASE}/fapi/v1/time")
        return r.json()

@app.get("/testnet/account")
async def testnet_account():
    return await binance(
        "GET",
        "/fapi/v2/account"
    )

@app.get("/testnet/positions")
async def testnet_positions():
    data = await binance(
        "GET",
        "/fapi/v2/positionRisk"
    )
    return [
        x for x in data
        if abs(float(x.get("positionAmt", "0"))) > 0
    ]

@app.get("/testnet/open-orders")
async def open_orders(symbol: str = "BTCUSDT"):
    return await binance(
        "GET",
        "/fapi/v1/openOrders",
        {"symbol": symbol.upper()}
    )

@app.post("/testnet/order")
async def place_order(order: Order):
    side = order.side.upper()
    typ = order.order_type.upper()

    if side not in {"BUY", "SELL"}:
        raise HTTPException(400, "side must be BUY or SELL")

    if typ not in {"MARKET", "LIMIT"}:
        raise HTTPException(400, "order_type must be MARKET or LIMIT")

    params = {
        "symbol": order.symbol.upper(),
        "side": side,
        "type": typ,
        "quantity": order.quantity,
        "newOrderRespType": "RESULT",
    }

    if order.position_side.upper() in {"BOTH", "LONG", "SHORT"}:
        params["positionSide"] = order.position_side.upper()

    if order.reduce_only:
        params["reduceOnly"] = "true"

    return await binance(
        "POST",
        "/fapi/v1/order",
        params
    )

@app.post("/testnet/close")
async def close_position(
    symbol: str = "BTCUSDT",
    quantity: str = "0",
    side: str = "SELL",
):
    if quantity == "0":
        raise HTTPException(400, "quantity required")

    return await binance(
        "POST",
        "/fapi/v1/order",
        {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": "MARKET",
            "quantity": quantity,
            "reduceOnly": "true",
            "newOrderRespType": "RESULT",
        }
    )

