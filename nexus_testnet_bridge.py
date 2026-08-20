"""Binance Futures Testnet bridge with strict validation and deterministic telemetry."""
from __future__ import annotations
import hashlib,hmac,logging,os,re,time
from decimal import Decimal,InvalidOperation
from typing import Any
from urllib.parse import urlencode
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI,HTTPException
from pydantic import BaseModel,Field,field_validator

load_dotenv(); logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"),format="%(asctime)s %(levelname)s %(name)s %(message)s"); logger=logging.getLogger("honeycomb.testnet.bridge")
BINANCE_BASE=os.getenv("BINANCE_TESTNET_URL",os.getenv("BINANCE_FUTURES_TESTNET_URL",os.getenv("BINANCE_TESTNET_BASE_URL","https://testnet.binancefuture.com"))).rstrip("/")
ENGINE_URL=os.getenv("ENGINE_URL","http://127.0.0.1:8000").rstrip("/")

def env_first(*names:str)->str:
    """Return the first configured environment value."""
    return next((os.getenv(n,"" ).strip() for n in names if os.getenv(n)),"")

BINANCE_KEY=env_first("BINANCE_TESTNET_API_KEY","BINANCE_API_KEY_TESTNET","BINANCE_FUTURES_API_KEY","BINANCE_API_KEY")
BINANCE_SECRET=env_first("BINANCE_TESTNET_SECRET","BINANCE_API_SECRET_TESTNET","BINANCE_FUTURES_API_SECRET","BINANCE_API_SECRET","BINANCE_SECRET_KEY")
app=FastAPI(title="Honeycomb Quantum Nexus Testnet Bridge",version="2.0.0",docs_url="/docs")

class Order(BaseModel):
    """Validated testnet order contract."""
    symbol:str=Field(default="BTCUSDT",pattern=r"^[A-Z0-9]{5,20}$")
    side:str
    quantity:str
    order_type:str="MARKET"
    position_side:str="BOTH"
    reduce_only:bool=False
    @field_validator("side")
    @classmethod
    def validate_side(cls,value:str)->str:
        value=value.upper()
        if value not in {"BUY","SELL"}: raise ValueError("side must be BUY or SELL")
        return value
    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls,value:str)->str:
        try: amount=Decimal(value)
        except (InvalidOperation,ValueError): raise ValueError("quantity must be numeric")
        if amount<=0: raise ValueError("quantity must be positive")
        return format(amount,"f")
    @field_validator("order_type")
    @classmethod
    def validate_type(cls,value:str)->str:
        value=value.upper()
        if value not in {"MARKET","LIMIT"}: raise ValueError("order_type must be MARKET or LIMIT")
        return value
    @field_validator("position_side")
    @classmethod
    def validate_position_side(cls,value:str)->str:
        value=value.upper()
        if value not in {"BOTH","LONG","SHORT"}: raise ValueError("position_side must be BOTH, LONG or SHORT")
        return value

def signed_params(params:dict[str,Any])->dict[str,Any]:
    """Create Binance HMAC-SHA256 parameters with bounded receive window."""
    if not BINANCE_SECRET: raise HTTPException(503,"Binance testnet secret is not configured")
    result=dict(params); result["timestamp"]=int(time.time()*1000); result["recvWindow"]=5000
    query=urlencode(result); result["signature"]=hmac.new(BINANCE_SECRET.encode(),query.encode(),hashlib.sha256).hexdigest(); return result

async def binance(method:str,path:str,params:dict[str,Any]|None=None,signed:bool=True)->Any:
    """Perform one bounded Binance testnet request; never targets mainnet."""
    if signed and not BINANCE_KEY: raise HTTPException(503,"Binance testnet API key is not configured")
    payload=signed_params(params or {}) if signed else (params or {})
    headers={"X-MBX-APIKEY":BINANCE_KEY} if BINANCE_KEY else {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0,connect=5.0)) as client:
            response=await client.request(method,BINANCE_BASE+path,params=payload,headers=headers)
        try: data=response.json()
        except Exception: data={"raw":response.text}
        if response.status_code>=400: raise HTTPException(response.status_code,data)
        return data
    except HTTPException: raise
    except httpx.HTTPError as exc: logger.error("binance_request_failed path=%s error=%s",path,exc); raise HTTPException(502,"Binance testnet upstream unavailable") from exc

async def engine_get(path:str)->Any:
    """Read-only proxy to the local execution engine."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response=await client.get(ENGINE_URL+path); response.raise_for_status(); return response.json()
    except httpx.HTTPError as exc: raise HTTPException(503,f"engine unavailable: {exc}") from exc

@app.get("/")
async def root()->dict[str,Any]: return {"service":"honeycomb-testnet-bridge","status":"online","exchange":"BINANCE_USDM_TESTNET","engine":ENGINE_URL}

@app.get("/health")
async def health()->dict[str,Any]: return {"ok":True,"service":"testnet-bridge","exchange":"BINANCE_USDM_TESTNET","credentials_configured":bool(BINANCE_KEY and BINANCE_SECRET),"engine_url":ENGINE_URL}

@app.get("/ready")
async def ready()->dict[str,Any]:
    engine_ok=False
    try: await engine_get("/health"); engine_ok=True
    except HTTPException: pass
    if not engine_ok: raise HTTPException(503,"engine not ready")
    return {"ready":True,"engine":True,"bridge":True}

@app.get("/status")
async def status()->dict[str,Any]:
    result={"bridge":"online","binance_testnet":"configured" if BINANCE_KEY and BINANCE_SECRET else "missing_credentials","engine":{"online":False}}
    try: result["engine"]={"online":True,"data":await engine_get("/health")}
    except HTTPException as exc: result["engine"]={"online":False,"error":exc.detail}
    return result

@app.get("/summary")
async def summary()->Any: return await engine_get("/summary")
@app.get("/positions")
async def positions()->Any: return await engine_get("/positions")
@app.get("/journal")
async def journal()->Any: return await engine_get("/journal")

@app.get("/testnet/time")
async def testnet_time()->Any: return await binance("GET","/fapi/v1/time",signed=False)
@app.get("/testnet/account")
async def testnet_account()->Any: return await binance("GET","/fapi/v2/account")
@app.get("/testnet/positions")
async def testnet_positions()->Any:
    data=await binance("GET","/fapi/v2/positionRisk")
    return [x for x in data if abs(float(x.get("positionAmt","0")))>0]
@app.get("/testnet/open-orders")
async def open_orders(symbol:str="BTCUSDT")->Any:
    if not re.fullmatch(r"[A-Z0-9]{5,20}",symbol.upper()): raise HTTPException(400,"invalid symbol")
    return await binance("GET","/fapi/v1/openOrders",{"symbol":symbol.upper()})

@app.post("/testnet/order")
async def place_order(order:Order)->Any:
    params={"symbol":order.symbol.upper(),"side":order.side,"type":order.order_type,"quantity":order.quantity,"newOrderRespType":"RESULT","positionSide":order.position_side}
    if order.reduce_only and order.position_side=="BOTH": params["reduceOnly"]="true"
    logger.info("testnet_order symbol=%s side=%s type=%s quantity=%s reduce_only=%s",order.symbol,order.side,order.order_type,order.quantity,order.reduce_only)
    return await binance("POST","/fapi/v1/order",params)

@app.post("/testnet/close")
async def close_position(symbol:str="BTCUSDT",quantity:str="0",side:str="SELL")->Any:
    if quantity=="0": raise HTTPException(400,"quantity required")
    order=Order(symbol=symbol,side=side,quantity=quantity,order_type="MARKET",position_side="BOTH",reduce_only=True)
    return await place_order(order)
