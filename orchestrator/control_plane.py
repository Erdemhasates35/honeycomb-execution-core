#!/usr/bin/env python3
"""Honeycomb deterministic control plane: inventory, quality, runtime telemetry and mode state."""
from __future__ import annotations
import hashlib,json,os,re,socket,subprocess,tempfile,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs,urlparse
ROOT=Path(__file__).resolve().parents[1]; PORT=int(os.getenv("CONTROL_PORT","8787")); HOST=os.getenv("CONTROL_HOST","127.0.0.1")
STATE=ROOT/"orchestrator"/"state.json"; REGISTRY=ROOT/"orchestrator"/"registry.json"; PIDFILE=ROOT/"runtime"/"control_plane.pid"; LOGDIR=ROOT/"logs"
SOURCE_EXT={".py",".js",".mjs",".cjs",".ts",".tsx",".go",".sh",".bash",".json"}; SKIP={".git","node_modules","__pycache__",".venv","venv",".next","dist","build"}

def load_dotenv()->None:
    """Load project configuration without printing credentials."""
    env=ROOT/".env"
    if not env.exists(): return
    for raw in env.read_text(errors="ignore").splitlines():
        line=raw.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        key,value=line.split("=",1); key=key.strip()
        if key and key not in os.environ: os.environ[key]=value.strip().strip('"').strip("'")

def safe_env()->dict[str,str]:
    """Return allowlisted settings and only SET/NOT_SET secret state."""
    names=["HONEYCOMB_MODE","AUTO_PAPER","AUTO_INTERVAL_SEC","TARGET_PROFIT_PERCENT","MAX_LOSS_PERCENT","TESTNET_PORT","TESTNET_RISK","TESTNET_LEVERAGE","TESTNET_TP_M","TESTNET_SL_P","TESTNET_HOLD_MAX","TESTNET_INTERVAL","TESTNET_COOLDOWN","TESTNET_MAX_POS_USDT","NET_MARGIN_TARGET_PCT","CONSECUTIVE_LOSS_THRESHOLD","SYMBOL_COOLDOWN_MIN","ERROR_REPEAT_THRESHOLD","MARGIN_PAUSE_MIN","ATR_PERCENTILE_FLOOR","MIN_ATR_PCT","LOW_VOL_ATR_PCT","LOW_VOL_RISK_MULT","LOW_VOL_CONFIDENCE","NORMAL_CONFIDENCE","FEE_RATE","COOLDOWN","LIVE_SYMBOLS","ENGINE_URL","BINANCE_TESTNET_URL","BINANCE_TESTNET_ALLOW_GENERIC_KEYS"]
    out={k:os.environ[k] for k in names if k in os.environ}
    for secret in ("BINANCE_TESTNET_API_KEY","BINANCE_TESTNET_SECRET","BINANCE_API_KEY","BINANCE_API_SECRET","BINANCE_SECRET"): out[secret]="SET" if os.getenv(secret) else "NOT_SET"
    return out

def sha256(path:Path)->str:
    """Return streaming SHA-256 for reproducible inventory."""
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
    return h.hexdigest()

def write_json_atomic(path:Path,payload:Any)->None:
    """Persist JSON atomically so a dashboard read can never observe a partial document."""
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=f".{path.name}.",suffix=".tmp",dir=str(path.parent),text=True)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as handle:
            json.dump(payload,handle,indent=2,ensure_ascii=False); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
        os.replace(tmp,path)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass

def load_registry()->dict[str,Any]:
    """Load registry and recover from empty/truncated/invalid JSON without losing its schema."""
    default={"project":ROOT.name,"control_plane":{"host":HOST,"port":PORT},"execution_ports":[8000,8100],"modes":["TESTNET","PAPER","LIVE"],"engines":[]}
    if not REGISTRY.exists(): return default
    try:
        raw=REGISTRY.read_text(encoding="utf-8").strip()
        if not raw: return default
        value=json.loads(raw)
        if not isinstance(value,dict): return default
        merged=dict(default); merged.update(value)
        if not isinstance(merged.get("engines"),list): merged["engines"]=[]
        return merged
    except (OSError,UnicodeError,json.JSONDecodeError,TypeError,ValueError):
        return default

def inventory()->dict[str,Any]:
    """Build source inventory and update registry hashes."""
    engines=[]; files=[]; patterns=("engine","alpha","brain","nexus","verify","sovereign","futures","scalp","orchestrator","control")
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SOURCE_EXT or any(p in SKIP for p in path.parts): continue
        rel=path.relative_to(ROOT)
        try:
            size=path.stat().st_size; digest=sha256(path); text=path.read_text(errors="ignore")[:200000] if size<2_000_000 and path.suffix!=".json" else ""
            score=sum(1 for item in patterns if item in path.name.lower() or item in text.lower()); files.append({"path":rel.as_posix(),"size":size,"sha256":digest})
            if score>=2: engines.append({"path":rel.as_posix(),"score":score,"sha256":digest})
        except Exception as exc: files.append({"path":rel.as_posix(),"error":str(exc)})
    data={"generated_at":time.time(),"files":files,"engines":sorted(engines,key=lambda x:(-x["score"],x["path"]))}; (ROOT/"runtime").mkdir(exist_ok=True)
    write_json_atomic(ROOT/"runtime"/"inventory.json",data)
    registry=load_registry(); registry["engines"]=data["engines"]; write_json_atomic(REGISTRY,registry)
    return data

def git_status()->dict[str,Any]:
    """Return branch and working tree state."""
    try:
        branch=subprocess.check_output(["git","branch","--show-current"],cwd=ROOT,text=True,stderr=subprocess.DEVNULL).strip(); status=subprocess.check_output(["git","status","--short"],cwd=ROOT,text=True,stderr=subprocess.DEVNULL)
        return {"branch":branch,"dirty":bool(status.strip()),"status":status.splitlines()[-100:]}
    except Exception as exc: return {"error":str(exc)}

def port_probe(port:int)->bool:
    """Probe a local TCP service."""
    sock=socket.socket(); sock.settimeout(.35)
    try: return sock.connect_ex(("127.0.0.1",port))==0
    finally: sock.close()

def recent_logs(limit:int=120)->list[dict[str,str]]:
    """Return recent logs with credential-bearing lines redacted."""
    rows=[]
    if not LOGDIR.exists(): return rows
    for path in sorted(LOGDIR.glob("*"),key=lambda x:x.stat().st_mtime if x.exists() else 0,reverse=True)[:8]:
        if not path.is_file(): continue
        try:
            for line in path.read_text(errors="replace").splitlines()[-limit:]:
                if re.search(r"(api[_ -]?key|secret|private[_ -]?key|token)",line,re.I): line="[REDACTED]"
                rows.append({"file":path.relative_to(ROOT).as_posix(),"line":line[-1000:]})
        except Exception: pass
    return rows[-limit:]

def database_stats()->list[dict[str,Any]]:
    """Read SQLite table counts without modifying databases."""
    import sqlite3
    result=[]
    for path in ROOT.rglob("*.db"):
        if any(p in SKIP for p in path.parts): continue
        try:
            with sqlite3.connect(str(path),timeout=1) as c:
                tables=c.execute("select name from sqlite_master where type='table'").fetchall(); counts={}
                for (table,) in tables[:50]:
                    try: counts[table]=int(c.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                    except Exception: pass
            result.append({"db":path.relative_to(ROOT).as_posix(),"tables":counts})
        except Exception as exc: result.append({"db":path.relative_to(ROOT).as_posix(),"error":str(exc)})
    return result

def quality_report()->dict[str,Any]:
    """Run the deterministic repository quality gate."""
    from orchestrator.quality_gate import write_report
    return write_report(ROOT)

def current_status()->dict[str,Any]:
    """Compose runtime, source, database and quality telemetry."""
    load_dotenv(); inv=inventory(); mode=os.getenv("HONEYCOMB_MODE","TESTNET").upper()
    if STATE.exists():
        try: mode=str(json.loads(STATE.read_text()).get("mode",mode)).upper()
        except Exception: pass
    return {"time":time.time(),"project":ROOT.name,"mode":mode,"control_plane":{"host":HOST,"port":PORT},"execution_ports":{"8000":port_probe(8000),"8100":port_probe(8100)},"pid":os.getpid(),"git":git_status(),"env":safe_env(),"engine_count":len(inv["engines"]),"source_file_count":len(inv["files"]),"databases":database_stats(),"quality":quality_report(),"launcher":str(ROOT/"run_nexus_testnet.sh") if (ROOT/"run_nexus_testnet.sh").exists() else None}

class Handler(BaseHTTPRequestHandler):
    """HTTP dashboard and control API."""
    def send_json(self,status:int,payload:Any)->None:
        body=json.dumps(payload,ensure_ascii=False).encode(); self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers(); self.wfile.write(body)
    def do_GET(self)->None:
        parsed=urlparse(self.path); query=parse_qs(parsed.query)
        if parsed.path=="/":
            body=(ROOT/"dashboard"/"index.html").read_bytes(); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.end_headers(); self.wfile.write(body); return
        if parsed.path=="/api/status": self.send_json(200,current_status()); return
        if parsed.path=="/api/engines": self.send_json(200,inventory()["engines"]); return
        if parsed.path=="/api/files": self.send_json(200,inventory()["files"]); return
        if parsed.path=="/api/quality": self.send_json(200,quality_report()); return
        if parsed.path=="/api/logs":
            try: limit=min(int(query.get("n",["120"])[0]),500)
            except Exception: limit=120
            self.send_json(200,recent_logs(limit)); return
        self.send_json(404,{"error":"not_found"})
    def do_POST(self)->None:
        if urlparse(self.path).path!="/api/mode": self.send_json(404,{"error":"not_found"}); return
        try: data=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))) or b"{}")
        except Exception: self.send_json(400,{"error":"invalid_json"}); return
        mode=str(data.get("mode","")).upper()
        if mode not in {"TESTNET","PAPER","LIVE"}: self.send_json(400,{"error":"mode must be TESTNET, PAPER or LIVE"}); return
        if mode=="LIVE" and os.getenv("LIVE_ARMED")!="1": self.send_json(403,{"error":"LIVE_ARMED=1 required"}); return
        write_json_atomic(STATE,{"mode":mode,"changed_at":time.time()}); self.send_json(200,{"ok":True,"mode":mode})
    def log_message(self,*args:Any)->None: return

def main()->None:
    """Start the control plane on the local device."""
    load_dotenv(); (ROOT/"runtime").mkdir(exist_ok=True); PIDFILE.write_text(str(os.getpid())); inventory(); print(f"HONEYCOMB CONTROL PLANE http://{HOST}:{PORT}",flush=True); ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()

if __name__=="__main__": main()
