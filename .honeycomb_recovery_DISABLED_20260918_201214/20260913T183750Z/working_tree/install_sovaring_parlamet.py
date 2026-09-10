import alpha_core  # noqa: E402
import ai_parliament  # noqa: E402

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# --------------------------------------------------------------- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [PARLIAMENT] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sovereign_parliament")

# ------------------------------------------------------------------ ENV ----
EXECUTION_MODE = os.getenv("EXECUTION_MODE", "PAPER").upper()   # PAPER | TEST | LIVE
LIVE_ARMED = os.getenv("LIVE_ARMED", "0") == "1"
IS_LIVE = EXECUTION_MODE == "LIVE" and LIVE_ARMED

SYMBOLS = [s.strip().upper() for s in os.getenv("LIVE_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT").split(",") if s.strip()]
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "3"))
SCAN_SEC = int(os.getenv("SCAN_INTERVAL_SEC", "45"))
BASE_RISK_PCT = float(os.getenv("LIVE_RISK", os.getenv("RISK_PCT", "0.05")))
LEV_MIN = int(float(os.getenv("LEV_MIN", "5")))
LEV_MAX = int(float(os.getenv("MAX_LEVERAGE", "20")))
MAX_NOTIONAL = float(os.getenv("MAX_POSITION_SIZE_USDT", "200"))
FEE_RATE = float(os.getenv("FEE_RATE", "0.0004"))
TECH_WEIGHT = float(os.getenv("TECH_WEIGHT", "0.45"))
AI_WEIGHT = float(os.getenv("AI_WEIGHT", "0.55"))
MIN_FINAL_CONF = float(os.getenv("MIN_FINAL_CONF", "60"))

BRIDGE_HOST = os.getenv("BRIDGE_HOST", "127.0.0.1")
BRIDGE_PORT = int(os.getenv("HONEYCOMB_BRIDGE_PORT", "8100"))

kernel = LiveKernel(venue="usdt", log_fn=lambda m: log.info(m))
kernel.load_exchange_info(SYMBOLS)

trail_engine = DynamicTrailingStopEngine(kernel, log_fn=lambda m: log.info(m))
order_breaker = CircuitBreaker(
    fail_threshold=int(os.getenv("BREAKER_FAIL_THRESHOLD", "4")),
    cooldown_sec=int(os.getenv("BREAKER_COOLDOWN_SEC", "180")),
)
audit = CryptographicAuditLedger(os.path.join(ROOT, "audit_ledger.jsonl"))

_journal: List[Dict[str, Any]] = []
_open_meta: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()
_last_votes: Dict[str, List[ai_parliament.Vote]] = {}
_decision_log: List[Dict[str, Any]] = []  # panel için: her sembol taramasının insan-okunur özeti


def _log_decision(symbol: str, opened: bool, reason: str, extra: Dict[str, Any]) -> None:
    with _lock:
        _decision_log.insert(0, {"ts": int(time.time()), "symbol": symbol, "opened": opened,
                                  "reason": reason, **extra})
        if len(_decision_log) > 150:
            _decision_log.pop()


# ========================================================== GERÇEK EQUITY ==
def get_wallet_equity() -> float:
    """
    kernel.balance_usdt() KASITLI olarak availableBalance (boş/kullanılabilir
    marj) döndürür — pozisyon boyutlandırma için doğru olan budur.
    Ama drawdown/tepe takibi için hesabın GERÇEK cüzdan bakiyesi (balance)
    gerekir; availableBalance başka pozisyonların/botların marj kullanımına
    göre dakikalar içinde büyük oynar ve sahte drawdown alarmı üretir.
    Bu yüzden burada aynı /fapi/v2/balance endpoint'i kernel üzerinden
    (kernel._http, imzalı) çağrılıp "balance" alanı okunuyor — kernel.py'a
    hiçbir değişiklik yapılmadı, sadece mevcut imzalı istek altyapısı
    farklı bir alan için kullanılıyor.
    """
    try:
        data = kernel._http("GET", kernel.v["balance"], {}, signed=True, weight=5)
        for a in data:
            if a.get("asset") == "USDT":
                return float(a.get("balance") or a.get("crossWalletBalance") or a.get("availableBalance") or 0)
    except Exception as e:
        log.warning("wallet equity alınamadı, availableBalance'a düşülüyor: %s", e)
        return kernel.balance_usdt()
    return kernel.balance_usdt()


# ============================================================== FONLAMA ====
def get_funding_rate(symbol: str) -> float:
    """Binance premiumIndex — public endpoint, imza gerekmez."""
    try:
        url = f"{kernel.v['rest']}{kernel.v['premium']}?symbol={symbol}"
        req = urllib.request.Request(url, headers={"User-Agent": "sovereign-parliament/1.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read().decode())
        return float(data.get("lastFundingRate", 0.0))
    except Exception as e:
        log.warning("funding rate alınamadı %s: %s", symbol, e)
        return 0.0


# ========================================================= SKOR BİRLEŞTİRME
def combine_scores(tech: Dict[str, Any], ai: ai_parliament.ParliamentResult) -> Dict[str, Any]:
    """
    Teknik skor (-100..100) ve AI skoru (-100..100) ağırlıklı birleştirilir.
    AI konseyi güvenilir çoğunluğa (MIN_QUORUM) ulaşamadıysa AI ağırlığı
    otomatik olarak teknik tarafa kaydırılır (asla sahte AI görüşüyle
    doldurulmaz).
    """
    tw, aw = TECH_WEIGHT, AI_WEIGHT
    if not ai.reliable:
        tw, aw = 1.0, 0.0
        log.warning("AI parlamentosu quorum'a ulaşamadı (oy=%d) — bu turda sadece teknik skor kullanılacak.", ai.quorum)
    final_score = tech["tech_score"] * tw + ai.ai_score * aw
    final_conf = abs(final_score)
    side = "LONG" if final_score > 0 else ("SHORT" if final_score < 0 else None)
    return {"final_score": final_score, "final_conf": final_conf, "side": side, "tw": tw, "aw": aw}


def dynamic_leverage(final_conf: float, regime: str) -> int:
    span = LEV_MAX - LEV_MIN
    lev = LEV_MIN + span * max(0.0, min(1.0, (final_conf - MIN_FINAL_CONF) / (100.0 - MIN_FINAL_CONF + 1e-9)))
    if regime == "HIGHVOL":
        lev *= 0.7
    return max(LEV_MIN, min(LEV_MAX, int(round(lev))))


# =============================================================== ANA DÖNGÜ =
def open_positions_list() -> List[Tuple[str, str]]:
    out = []
    with _lock:
        for sym, meta in _open_meta.items():
            out.append((sym, meta["side"]))
    return out


def scan_symbol(symbol: str) -> None:
    with _lock:
        if symbol in _open_meta:
            return
        if len(_open_meta) >= MAX_POSITIONS:
            return

    equity = get_wallet_equity()
    tech = alpha_core.get_technical_decision(symbol, equity, open_positions_list())
    if not tech["allow"]:
        defense = tech.get("defense", 0)
        if defense >= 2:
            kalan_dk = alpha_core.get_defense_remaining_sec() // 60
            sebep = (f"Koruma Modu (Sert Kilit) aktif — beklenti negatif ya da cüzdan tepe "
                     f"değerinden düştü. Kilit ~{kalan_dk} dk sonra kendiliğinden açılacak.")
        elif tech["regime"] == "DEATH":
            sebep = f"Piyasa çok durgun (ATR%={tech['atr_pct']:.3f}) — hareket masrafı karşılamıyor."
        elif tech.get("reason") == "Korelasyon kalkanı aktif":
            sebep = "Aynı gruptaki başka bir sembolde zaten aynı yönde pozisyon var."
        else:
            yon_metni = "yön belirsiz" if tech["side"] is None else f'{tech["side"]} yönü zayıf'
            esik = 54 if tech["regime"] == "RANGE" else 57
            sebep = f"Teknik güven eşiği geçmedi ({yon_metni}, güven={tech['confidence']:.0f}, gereken>={esik})."
        log.info("AÇILMADI %s -> SEBEP: %s [rejim=%s skor=%.1f]", symbol, sebep, tech["regime"], tech["tech_score"])
        _log_decision(symbol, False, sebep, {"regime": tech["regime"], "tech_score": round(tech["tech_score"], 1),
                                              "confidence": round(tech["confidence"], 1)})
        return

    snapshot = {
        "price": None,
        "regime": tech["regime"],
        "atr_pct": tech["atr_pct"],
        "tech_score": tech["tech_score"],
        "indicators": tech["indicators"],
        "tf_scores": tech["tf_details"],
        "open_positions": len(_open_meta),
    }
    try:
        bid, ask, mid = kernel.book(symbol)
        snapshot["price"] = mid
    except Exception as e:
        log.warning("book alınamadı %s: %s", symbol, e)
        return

    ai_result = ai_parliament.run_parliament(symbol, snapshot)
    combo = combine_scores(tech, ai_result)
    _last_votes[symbol] = ai_result.votes

    log.info(
        "KARAR %s | teknik=%.1f ai=%.1f(quorum=%d/güvenilir=%s) final=%.1f yön=%s | rejim=%s",
        symbol, tech["tech_score"], ai_result.ai_score, ai_result.quorum, ai_result.reliable,
        combo["final_score"], combo["side"], tech["regime"],
    )
    for v in ai_result.votes:
        log.info("  oy[%s|%s] yön=%s güven=%.0f ağırlık=%.2f gerekçe=%s%s",
                  v.agent_id, v.model, v.direction, v.confidence, v.weight, v.reason,
                  (" HATA=" + v.error) if v.error else "")

    if combo["side"] is None or combo["final_conf"] < MIN_FINAL_CONF:
        sebep = f"Teknik+AI birleşik güveni yetersiz ({combo['final_conf']:.0f} < {MIN_FINAL_CONF:.0f})."
        log.info("AÇILMADI %s -> SEBEP: %s [teknik=%.1f ai=%.1f]", symbol, sebep, tech["tech_score"], ai_result.ai_score)
        _log_decision(symbol, False, sebep, {"regime": tech["regime"], "tech_score": round(tech["tech_score"], 1),
                                              "ai_score": round(ai_result.ai_score, 1),
                                              "final_conf": round(combo["final_conf"], 1)})
        return

    if alpha_core.correlation_blocked(symbol, combo["side"], open_positions_list()):
        sebep = "Korelasyon kalkanı: aynı gruptan başka sembolde aynı yönde pozisyon zaten açık."
        log.info("AÇILMADI %s -> SEBEP: %s", symbol, sebep)
        _log_decision(symbol, False, sebep, {"regime": tech["regime"]})
        return

    lev = dynamic_leverage(combo["final_conf"], tech["regime"])
    risk_pct = BASE_RISK_PCT * tech["risk_mult"]
    tp_pct = tech["tp_atr_mult"] * tech["atr_pct"]
    sl_pct = tech["sl_atr_mult"] * tech["atr_pct"]
    funding = get_funding_rate(symbol)
    # Fonlama pozisyon yönünün aleyhineyse (long iken pozitif funding gibi)
    # güveni ve dolayısıyla boyutu hafifçe düşür — ekstra maliyet kalemi.
    funding_penalty = 1.0
    if (combo["side"] == "LONG" and funding > 0.0003) or (combo["side"] == "SHORT" and funding < -0.0003):
        funding_penalty = 0.8
        risk_pct *= funding_penalty

    log.info(
        "EMİR HAZIRLA %s %s | lev=%dx risk=%.3f%% tp=%.3f%% sl=%.3f%% funding=%.5f mode=%s live_armed=%s",
        combo["side"], symbol, lev, risk_pct * 100, tp_pct, sl_pct, funding, EXECUTION_MODE, LIVE_ARMED,
    )

    if not IS_LIVE:
        sebep = "LIVE_ARMED kapalı — karar üretildi ama gerçek emir GÖNDERİLMEDİ (aşağıya bakın)."
        log.warning("GÖNDERİLMEDİ %s %s -> SEBEP: %s lev=%dx risk=%.3f%%", combo["side"], symbol, sebep, lev, risk_pct * 100)
        _log_decision(symbol, False, sebep, {"regime": tech["regime"], "side": combo["side"],
                                              "confidence": round(combo["final_conf"], 1), "leverage": lev})
        return

    if not order_breaker.allow():
        kalan = order_breaker.time_until_reset()
        log.warning("EMİR DEVRE KESİCİ AÇIK (%s) — ard arda borsa hatası oldu, ~%.0fsn beklenecek.", symbol, kalan)
        return

    try:
        res = kernel.open_market(symbol, combo["side"], risk_pct, lev, tp_pct, sl_pct, max_notional=MAX_NOTIONAL)
        order_breaker.record_success()
    except Exception as e:
        order_breaker.record_failure()
        sebep = f"Borsa emri reddetti/başarısız oldu: {e}"
        log.error("AÇILAMADI %s -> SEBEP: %s", symbol, sebep)
        _log_decision(symbol, False, sebep, {"regime": tech["regime"], "side": combo["side"]})
        return

    open_fee = res["entry"] * res["qty"] * FEE_RATE
    with _lock:
        _open_meta[symbol] = {
            "side": combo["side"], "entry": res["entry"], "qty": res["qty"],
            "tp": res["tp"], "sl": res["sl"], "oid": res["oid"],
            "lev": lev, "open_fee": open_fee, "funding_at_open": funding,
            "ts": time.time(), "tech_score": tech["tech_score"], "ai_score": ai_result.ai_score,
            "confidence": combo["final_conf"], "regime": tech["regime"], "trail_stage": 0,
        }
    trail_engine.register(symbol, combo["side"], res["entry"], res["tp"], res["sl"])
    audit.append({
        "event": "OPEN", "symbol": symbol, "side": combo["side"], "entry": res["entry"],
        "qty": res["qty"], "leverage": lev, "tp": res["tp"], "sl": res["sl"],
        "confidence": round(combo["final_conf"], 1), "regime": tech["regime"],
        "tech_score": round(tech["tech_score"], 2), "ai_score": round(ai_result.ai_score, 2),
    })
    log.info("AÇILDI %s %s entry=%.6f qty=%s lev=%dx TP=%.6f SL=%.6f", combo["side"], symbol,
              res["entry"], res["qty"], lev, res["tp"], res["sl"])
    _log_decision(symbol, True, f"Pozisyon açıldı: {combo['side']} @ {res['entry']:.6f}, kaldıraç {lev}x",
                  {"regime": tech["regime"], "side": combo["side"], "entry": res["entry"],
                   "leverage": lev, "confidence": round(combo["final_conf"], 1)})


def check_closed_positions() -> None:
    """Borsada kapanmış pozisyonları tespit edip PnL/masraf muhasebesini kapatır."""
    with _lock:
        symbols = list(_open_meta.keys())
    for symbol in symbols:
        with _lock:
            meta = _open_meta.get(symbol)
        if not meta:
            continue
        try:
            real_amt = kernel.position_amt(symbol, meta["side"])
        except Exception as e:
            log.warning("pozisyon kontrol hatası %s: %s", symbol, e)
            continue
        if real_amt > 0:
            continue  # hâlâ açık

        try:
            bid, ask, mid = kernel.book(symbol)
            exit_px = mid
        except Exception:
            exit_px = meta["entry"]

        close_notional = exit_px * meta["qty"]
        close_fee = close_notional * FEE_RATE
        if meta["side"] == "LONG":
            raw = (exit_px - meta["entry"]) * meta["qty"]
        else:
            raw = (meta["entry"] - exit_px) * meta["qty"]
        total_fees = meta["open_fee"] + close_fee
        net = raw - close_fee
        hold_sec = time.time() - meta["ts"]
        rec = {
            "symbol": symbol, "side": meta["side"], "entry": meta["entry"], "exit": exit_px,
            "qty": meta["qty"], "leverage": meta["lev"], "raw_pnl": round(raw, 6),
            "open_fee": round(meta["open_fee"], 6), "close_fee": round(close_fee, 6),
            "total_fees": round(total_fees, 6), "net_pnl": round(net, 6),
            "hold_sec": round(hold_sec, 1), "regime": meta["regime"],
            "confidence": meta["confidence"], "closed_ts": int(time.time()),
        }
        with _lock:
            _journal.insert(0, rec)
            if len(_journal) > 300:
                _journal.pop()
            _open_meta.pop(symbol, None)

        alpha_core.on_trade_closed(symbol, meta["side"], net, meta["confidence"], meta["regime"])
        votes = _last_votes.get(symbol, [])
        was_profitable = {meta["side"]: net > 0, ("SHORT" if meta["side"] == "LONG" else "LONG"): net <= 0}
        ai_parliament.settle_round(votes, was_profitable)
        trail_engine.forget(symbol)
        audit.append({
            "event": "CLOSE", "symbol": symbol, "side": meta["side"], "entry": meta["entry"],
            "exit": exit_px, "qty": meta["qty"], "net_pnl": rec["net_pnl"], "total_fees": rec["total_fees"],
            "hold_sec": rec["hold_sec"], "regime": meta["regime"],
        })

        log.info(
            "KAPANDI %s %s | entry=%.6f exit=%.6f net=%.6f (ham=%.6f masraf=%.6f) hold=%.0fs",
            meta["side"], symbol, meta["entry"], exit_px, net, raw, total_fees, hold_sec,
        )


def manage_trailing_stops() -> None:
    """
    DİNAMİK STOP-LOSS: artık live/kernel.py içindeki gerçek
    DynamicTrailingStopEngine sınıfı kullanılıyor (aynı mantık, tek
    yerde tanımlı — mükerrer kod yok). Pozisyon açıldığında
    trail_engine.register() çağrılır, burada sadece update() ile
    güncel fiyat beslenir.
    """
    with _lock:
        symbols = list(_open_meta.keys())
    for symbol in symbols:
        try:
            bid, ask, mid = kernel.book(symbol)
        except Exception:
            continue
        new_sl = trail_engine.update(symbol, mid)
        if new_sl is not None:
            with _lock:
                if symbol in _open_meta:
                    _open_meta[symbol]["sl"] = new_sl


def main_loop() -> None:
    log.info(
        "ONLINE | mode=%s live_armed=%s symbols=%s max_pos=%d scan=%ds tech_w=%.2f ai_w=%.2f",
        EXECUTION_MODE, LIVE_ARMED, SYMBOLS, MAX_POSITIONS, SCAN_SEC, TECH_WEIGHT, AI_WEIGHT,
    )
    if not IS_LIVE:
        log.warning(
            "CANLI EMİR KAPALI (EXECUTION_MODE=%s, LIVE_ARMED=%s). Motor GERÇEK piyasa verisiyle "
            "GERÇEK kararlar üretmeye devam ediyor, sadece borsaya emir göndermiyor. "
            "Gerçekten canlıya almak için .env içinde EXECUTION_MODE=LIVE ve LIVE_ARMED=1 yapın.",
            EXECUTION_MODE, LIVE_ARMED,
        )
    while True:
        try:
            check_closed_positions()
            if IS_LIVE:
                manage_trailing_stops()
            for symbol in SYMBOLS:
                scan_symbol(symbol)
                time.sleep(1.2)  # ajan/istek yükünü sembol başına yay
            time.sleep(SCAN_SEC)
        except KeyboardInterrupt:
            log.info("Durduruldu.")
            break
        except Exception as e:
            log.error("DÖNGÜ HATASI: %s", e)
            time.sleep(10)


# ========================================================== BRIDGE HTTP API
def _render_dashboard() -> str:
    with _lock:
        journal = list(_journal[:40])
        positions = [{"symbol": s, **m} for s, m in _open_meta.items()]
        decisions = list(_decision_log[:60])
    total_net = sum(r["net_pnl"] for r in journal)
    wins = len([r for r in journal if r["net_pnl"] > 0])
    total = len(journal)
    winrate = (wins / total * 100) if total else 0.0

    def esc(x: Any) -> str:
        return str(x).replace("<", "&lt;").replace(">", "&gt;")

    pos_rows = "".join(
        f"<tr><td>{esc(p['symbol'])}</td><td class='{'long' if p['side']=='LONG' else 'short'}'>{p['side']}</td>"
        f"<td>{p['entry']:.6f}</td><td>{p['lev']}x</td><td>{esc(p['regime'])}</td>"
        f"<td>{p['confidence']:.0f}</td></tr>" for p in positions
    ) or "<tr><td colspan='6' class='muted'>Açık pozisyon yok</td></tr>"

    j_rows = "".join(
        f"<tr><td>{esc(r['symbol'])}</td><td class='{'long' if r['side']=='LONG' else 'short'}'>{r['side']}</td>"
        f"<td class='{'pnlpos' if r['net_pnl']>=0 else 'pnlneg'}'>{r['net_pnl']:+.4f}</td>"
        f"<td>{r['total_fees']:.4f}</td><td>{r['hold_sec']:.0f}s</td><td>{esc(r['regime'])}</td></tr>"
        for r in journal
    ) or "<tr><td colspan='6' class='muted'>Henüz kapanan işlem yok</td></tr>"

    d_rows = "".join(
        f"<tr><td>{time.strftime('%H:%M:%S', time.localtime(d['ts']))}</td><td>{esc(d['symbol'])}</td>"
        f"<td class='{'long' if d.get('opened') else 'muted'}'>{'AÇILDI' if d.get('opened') else 'açılmadı'}</td>"
        f"<td>{esc(d.get('reason',''))}</td></tr>" for d in decisions
    ) or "<tr><td colspan='4' class='muted'>Henüz karar yok</td></tr>"

    return f"""<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sovereign Parliament — Panel</title>
<meta http-equiv="refresh" content="8">
<style>
body{{background:#0b0f14;color:#d7e0e8;font-family:system-ui,sans-serif;margin:0;padding:16px}}
h1{{font-size:18px;color:#7fd1ff;margin:0 0 4px}}
.sub{{color:#7a8a99;font-size:13px;margin-bottom:16px}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px}}
.card{{background:#121820;border:1px solid #223;border-radius:10px;padding:12px 16px;min-width:130px}}
.card .v{{font-size:20px;font-weight:700}}
.card .l{{font-size:11px;color:#7a8a99;text-transform:uppercase}}
table{{width:100%;border-collapse:collapse;margin-bottom:24px;font-size:13px}}
th{{text-align:left;color:#7a8a99;font-weight:500;border-bottom:1px solid #223;padding:6px}}
td{{padding:6px;border-bottom:1px solid #182028}}
.long{{color:#5ee6a0}} .short{{color:#ff7b7b}} .muted{{color:#5a6b78}}
.pnlpos{{color:#5ee6a0;font-weight:600}} .pnlneg{{color:#ff7b7b;font-weight:600}}
h2{{font-size:14px;color:#9fb3c2;margin:0 0 8px}}
</style></head><body>
<h1>SOVEREIGN PARLIAMENT — Canlı Panel</h1>
<div class="sub">mod={esc(EXECUTION_MODE)} | live_armed={LIVE_ARMED} | 8sn'de bir otomatik yenilenir</div>
<div class="cards">
  <div class="card"><div class="v {'pnlpos' if total_net>=0 else 'pnlneg'}">{total_net:+.4f}</div><div class="l">Net K/Z (USDT)</div></div>
  <div class="card"><div class="v">{winrate:.0f}%</div><div class="l">Kazanma Oranı</div></div>
  <div class="card"><div class="v">{len(positions)}/{MAX_POSITIONS}</div><div class="l">Açık Pozisyon</div></div>
  <div class="card"><div class="v">{alpha_core.get_risk_multiplier():.2f}x</div><div class="l">Risk Çarpanı</div></div>
  <div class="card"><div class="v">{alpha_core.get_defense_level()}</div><div class="l">Koruma Seviyesi</div></div>
</div>
<h2>Açık Pozisyonlar</h2>
<table><tr><th>Sembol</th><th>Yön</th><th>Giriş</th><th>Kaldıraç</th><th>Rejim</th><th>Güven</th></tr>{pos_rows}</table>
<h2>Son Kapanan İşlemler</h2>
<table><tr><th>Sembol</th><th>Yön</th><th>Net K/Z</th><th>Masraf</th><th>Süre</th><th>Rejim</th></tr>{j_rows}</table>
<h2>Son Kararlar (neden açıldı / açılmadı)</h2>
<table><tr><th>Saat</th><th>Sembol</th><th>Durum</th><th>Sebep</th></tr>{d_rows}</table>
</body></html>"""


class BridgeHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path in ("/", "/panel"):
            self._send_html(_render_dashboard())
        elif path == "/health":
            self._send(200, {"ok": True, "ts": int(time.time())})
        elif path == "/status":
            self._send(200, {
                "mode": EXECUTION_MODE, "live_armed": LIVE_ARMED, "symbols": SYMBOLS,
                "open_positions": len(_open_meta), "max_positions": MAX_POSITIONS,
            })
        elif path == "/positions":
            with _lock:
                self._send(200, [{"symbol": s, **m} for s, m in _open_meta.items()])
        elif path == "/journal":
            with _lock:
                self._send(200, _journal[:100])
        elif path == "/summary":
            with _lock:
                total_net = sum(r["net_pnl"] for r in _journal)
                wins = len([r for r in _journal if r["net_pnl"] > 0])
                total = len(_journal)
            self._send(200, {
                "mode": EXECUTION_MODE, "live_armed": LIVE_ARMED,
                "open_positions": len(_open_meta), "closed_trades": total,
                "win_rate": round(wins / total, 4) if total else None,
                "total_net_pnl": round(total_net, 6),
                "risk_mult": alpha_core.get_risk_multiplier(),
                "defense_level": alpha_core.get_defense_level(),
            })
        elif path == "/audit":
            ok, bad_line = audit.verify_chain()
            self._send(200, {"chain_intact": ok, "broken_at_line": bad_line, "ledger_path": audit.path})
        else:
            self._send(404, {"error": "NOT_FOUND"})

    def log_message(self, *_args: Any) -> None:
        return


def start_bridge_server() -> None:
    server = ThreadingHTTPServer((BRIDGE_HOST, BRIDGE_PORT), BridgeHandler)
    log.info("BRIDGE API http://%s:%d (ui_control_plane.py BRIDGE_URL ile uyumlu)", BRIDGE_HOST, BRIDGE_PORT)
    server.serve_forever()


def main() -> None:
    t = threading.Thread(target=start_bridge_server, daemon=True)
    t.start()
    main_loop()


if __name__ == "__main__":
    main()
SOVEREIGN_ENGINE_EOF

#echo "[5/5] live/__init__.py yaziliyor..."
cat > live/__init__.py << 'INIT_EOF'
from .kernel import (
    LiveKernel,
    TokenBucket,
    SingleFlight,
    CryptographicAuditLedger,
    CircuitBreaker,
    DynamicTrailingStopEngine,
    PurePythonWebSocketClient,
    load_env,
    sma,
    ema,
    wma,
    rsi,
    atr,
    macd,
    bollinger_bands,
    stochastic,
    vwap,
    supertrend,
    adx,
    cci,
    obv,
    roc,
    williams_r,
    mfi,
)
INIT_EOF

#echo "syntax kontrolu..."
#python3 -m py_compile live/kernel.py live/__init__.py alpha_core.py ai_parliament.py sovereign_parliament_engine.py
#echo "import kontrolu (kernel.py + __init__.py birlikte yukleniyor mu)..."
#python3 -c "import live; print('live paketi basariyla yuklendi:', sorted([n for n in dir(live) if not n.startswith('_')]))"
#echo "TAMAM. Calistirmak icin:  python3 sovereign_parliament_engine.py"
#echo "Panel: http://127.0.0.1:8100/  (Termux tarayicisindan acabilirsiniz)"
#echo "Denetim zinciri kontrolu: http://127.0.0.1:8100/audit"
#echo "Once .env dosyanizda su degiskenlerin oldugundan emin olun:"
#echo "  EXECUTION_MODE, LIVE_ARMED, LIVE_SYMBOLS, MAX_POSITIONS, LEV_MIN, MAX_LEVERAGE,"
#echo "  MAX_POSITION_SIZE_USDT, LIVE_RISK, FEE_RATE, TECH_WEIGHT, AI_WEIGHT, MIN_FINAL_CONF,"
#echo "  DEFENSE_COOLDOWN_SEC, BREAKER_FAIL_THRESHOLD, BREAKER_COOLDOWN_SEC,"
#echo "  OPENROUTER_API_KEY (zorunlu), GOOGLE_API_KEY / XAI_API_KEY / ANTHROPIC_API_KEY (istege bagli),"
#echo "  BINANCE_API_KEY, BINANCE_SECRET_KEY, HONEYCOMB_BRIDGE_PORT"
#echo "NOT: live/kernel.py bu kurulumla YENIDEN YAZILDI (eksik CircuitBreaker/AuditLedger/"
#echo "TrailingStop/WebSocketClient siniflari ve indikator kutuphanesi eklendi). Eski"
#echo "LiveKernel sinifinin emir/HMAC/rate-limit mantigina TEK SATIR dokunulmadi."
