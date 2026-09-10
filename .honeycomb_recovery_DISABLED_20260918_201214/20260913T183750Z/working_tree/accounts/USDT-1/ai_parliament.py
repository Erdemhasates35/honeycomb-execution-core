#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI PARLIAMENT — çoklu-ajan karar konseyi
=========================================
- OpenRouter'daki GÜNCEL ücretsiz modelleri RUNTIME'da keşfeder
  (openrouter.ai/api/v1/models -> pricing.prompt==0 filtre). Model isimleri
  hardcode edilip zamanla bozulmaz; kodda tek bir model adı bile yazılı DEĞİL.
- Ek olarak GOOGLE_API_KEY (Gemini), XAI_API_KEY (Grok), ANTHROPIC_API_KEY
  (Claude) tanımlıysa bunlar NATIVE API'leri üzerinden ekstra oy veren
  ajanlar olarak konseye eklenir.
- En az 10 ajan: farklı roller (trend, mean-reversion, risk, rejim/volatilite,
  fonlama/maliyet, karşıt görüş/devil's advocate, çoklu-zaman-dilimi
  sentezleyici, üretken-makro, üretken-öz-eleştiri, likidite/slipaj).
- Bir ajan çağrısı BAŞARISIZ olursa o ajan o turda sayılmaz (loglanır) —
  ASLA sahte/mock bir oyla değiştirilmez. Sistemin teknik (alpha_core)
  omurgası zaten gerçek piyasa verisiyle bağımsız çalışır; AI parlamentosu
  tamamen düşse bile motor "mock veri" üretmez, sadece AI ağırlığını 0'a
  düşürür.
- Dinamik skorlama: her ajanın geçmiş isabet oranı SQLite'ta tutulur ve
  oy ağırlığı (0.4-1.6 aralığında) buna göre otomatik güncellenir.
- Her tur, her ajanın ham cevabı + ağırlığı + gerekçesi ayrı ayrı loglanır
  (izlenebilirlik / "loglardan analaşılır takip").
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "parliament.db")
OR_MODELS_URL = "https://openrouter.ai/api/v1/models"
OR_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
GEMINI_URL_TMPL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
XAI_URL = "https://api.x.ai/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

MODEL_CACHE_TTL_SEC = int(os.getenv("OR_MODEL_CACHE_TTL_SEC", "21600"))  # 6 saat
AGENT_TIMEOUT_SEC = float(os.getenv("PARLIAMENT_AGENT_TIMEOUT_SEC", "9"))
MIN_QUORUM = int(os.getenv("PARLIAMENT_MIN_QUORUM", "3"))  # bu sayının altında oy varsa AI sonucu güvensiz sayılır

# ------------------------------------------------------------------ DB -----
def _conn():
    return sqlite3.connect(DB_PATH, timeout=12)


def init_db() -> None:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS agent_weight(
                agent_id TEXT PRIMARY KEY,
                weight REAL NOT NULL DEFAULT 1.0,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                last_ts INTEGER
            );
            CREATE TABLE IF NOT EXISTS vote_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER, symbol TEXT, agent_id TEXT, model TEXT,
                direction TEXT, confidence REAL, weight REAL,
                latency_ms INTEGER, reason TEXT, error TEXT
            );
            CREATE TABLE IF NOT EXISTS model_cache(
                id INTEGER PRIMARY KEY CHECK (id = 1),
                ts INTEGER, payload TEXT
            );
            """
        )
        c.commit()


init_db()


def get_weight(agent_id: str) -> float:
    with _conn() as c:
        r = c.execute("SELECT weight FROM agent_weight WHERE agent_id=?", (agent_id,)).fetchone()
        return float(r[0]) if r else 1.0


def update_weight(agent_id: str, was_correct: bool) -> float:
    """Kazanma/kaybetme sonrası ajan ağırlığını 0.4-1.6 aralığında günceller."""
    with _conn() as c:
        r = c.execute("SELECT weight, wins, losses FROM agent_weight WHERE agent_id=?", (agent_id,)).fetchone()
        w, wins, losses = (r if r else (1.0, 0, 0))
        if was_correct:
            w = min(1.6, w * 1.06)
            wins += 1
        else:
            w = max(0.4, w * 0.90)
            losses += 1
        c.execute(
            "INSERT OR REPLACE INTO agent_weight(agent_id, weight, wins, losses, last_ts) VALUES(?,?,?,?,?)",
            (agent_id, w, wins, losses, int(time.time())),
        )
        c.commit()
        return w


def log_vote(symbol: str, agent_id: str, model: str, direction: Optional[str],
             confidence: float, weight: float, latency_ms: int,
             reason: str, error: str = "") -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO vote_log(ts,symbol,agent_id,model,direction,confidence,weight,latency_ms,reason,error) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (int(time.time()), symbol, agent_id, model, direction, confidence, weight, latency_ms, reason[:400], error[:300]),
        )
        c.commit()


# ------------------------------------------------------- MODEL DISCOVERY ---
def _http_json(url: str, headers: Dict[str, str], body: Optional[bytes] = None,
                method: str = "GET", timeout: float = 10.0) -> Any:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def discover_free_openrouter_models(limit: int = 30) -> List[str]:
    """
    openrouter.ai/api/v1/models üzerinden pricing.prompt==0 VE
    pricing.completion==0 olan modelleri canlı çeker. Böylece kodda
    tarihi geçmiş / uydurma model adı riski sıfırlanır. Başarısız olursa
    boş liste döner — çağıran taraf bunu "AI parlamentosu bu turda küçük"
    olarak ele alır, ASLA sahte model adıyla devam etmez.
    """
    with _conn() as c:
        row = c.execute("SELECT ts, payload FROM model_cache WHERE id=1").fetchone()
    now = int(time.time())
    if row and now - row[0] < MODEL_CACHE_TTL_SEC:
        try:
            return json.loads(row[1])
        except Exception:
            pass
    try:
        data = _http_json(OR_MODELS_URL, {"User-Agent": "ai-parliament/1.0"}, timeout=10)
        models = data.get("data", [])
        free = []
        for m in models:
            pricing = m.get("pricing", {}) or {}
            try:
                p_prompt = float(pricing.get("prompt", "1") or "1")
                p_compl = float(pricing.get("completion", "1") or "1")
            except (TypeError, ValueError):
                continue
            if p_prompt == 0.0 and p_compl == 0.0:
                free.append((m.get("id"), int(m.get("context_length") or 0)))
        free.sort(key=lambda x: -x[1])
        ids = [f[0] for f in free if f[0]][:limit]
        with _conn() as c:
            c.execute("INSERT OR REPLACE INTO model_cache(id, ts, payload) VALUES(1,?,?)",
                      (now, json.dumps(ids)))
            c.commit()
        return ids
    except Exception:
        # Ağ yoksa önbellekteki en son bilinen (eski olsa bile) listeyi kullan
        if row:
            try:
                return json.loads(row[1])
            except Exception:
                return []
        return []


# ------------------------------------------------------------- AGENTS ------
# 10 sabit rol. Model ataması dinamik havuzdan round-robin yapılır — rol
# tanımı SİSTEM PROMPT'unda, model kimliğinde değil (böylece hangi ücretsiz
# model o an mevcutsa onunla çalışır).
AGENT_ROLES: List[Dict[str, str]] = [
    {"id": "trend_hunter", "kind": "financial",
     "prompt": "Sen bir trend/momentum vadeli işlem analistisin. Sadece trend gücü ve momentuma odaklan."},
    {"id": "mean_reversion", "kind": "financial",
     "prompt": "Sen bir ortalamaya dönüş (mean-reversion) ve piyasa yapısı analistisin. Aşırı alım/satım bölgelerini ara."},
    {"id": "risk_guardian", "kind": "financial",
     "prompt": "Sen bir risk yöneticisisin. Öncelik sermaye korumadır; şüpheli durumda FLAT öner."},
    {"id": "regime_vol", "kind": "financial",
     "prompt": "Sen bir volatilite/rejim analistisin. Piyasanın trend mi, range mi, yüksek volatilite mi olduğuna odaklan."},
    {"id": "funding_carry", "kind": "financial",
     "prompt": "Sen fonlama oranı ve taşıma maliyeti (funding/carry) analistisin. Fonlama yönün aleyhineyse pozisyonu zayıflat."},
    {"id": "liquidity_slip", "kind": "financial",
     "prompt": "Sen likidite ve slipaj/emir defteri analistisin. İnce likiditede agresif emri reddet."},
    {"id": "mtf_synthesizer", "kind": "financial",
     "prompt": "Sen çoklu zaman dilimi (1m-4h) sentezleyicisisin. Kısa ve uzun vadeyi birlikte değerlendir."},
    {"id": "devils_advocate", "kind": "generative",
     "prompt": "Sen karşıt görüşü savunan bir eleştirmensin. Diğer analistlerin gözden kaçırabileceği riski bul."},
    {"id": "macro_narrator", "kind": "generative",
     "prompt": "Sen makro anlatı ve piyasa psikolojisi uzmanısın. Fiyat hareketinin arkasındaki olası anlatıyı değerlendir."},
    {"id": "self_critic", "kind": "generative",
     "prompt": "Sen sistemin öz-eleştiri ajanısın. Verilen teknik skorun aşırı iyimser/kötümser olup olmadığını sorgula."},
    {"id": "macro_horizon", "kind": "financial",
     "prompt": "Sen günlük/haftalık/aylık zaman diliminden bakan bir makro yatırımcısın. Kısa vadeli gürültüyü göz ardı et, büyük tabloya odaklan."},
    {"id": "scalper_1m", "kind": "financial",
     "prompt": "Sen sadece 1-3 dakikalık verilere bakan bir scalper'sın. Anlık mikro-yapı bozulmalarına odaklan."},
    {"id": "breakout_hunter", "kind": "financial",
     "prompt": "Sen kırılım (breakout) avcısısın. Sıkışma sonrası hacimli kırılımları ara, yalancı kırılımlara dikkat et."},
    {"id": "volatility_arb", "kind": "financial",
     "prompt": "Sen volatilite arbitrajcısısın. Gerçekleşen volatilite ile ATR bandı arasındaki uyumsuzluğa bak."},
    {"id": "orderflow_reader", "kind": "financial",
     "prompt": "Sen emir akışı (order flow) okuyucususun. Hacim/OBV ve fiyat uyumsuzluklarına (divergence) odaklan."},
    {"id": "macro_correlation", "kind": "financial",
     "prompt": "Sen kripto-makro korelasyon analistisin (BTC dominansı, toplam piyasa yönü). Sembolün liderlerle uyumuna bak."},
    {"id": "session_timing", "kind": "financial",
     "prompt": "Sen seans zamanlama analistisin (Asya/Avrupa/ABD seansları). Likidite ve volatilitenin seansa göre değiştiğini dikkate al."},
    {"id": "news_narrative", "kind": "generative",
     "prompt": "Sen piyasa anlatısı ve haber akışı yorumcususun. Verilen teknik tabloya uyan olası bir piyasa anlatısı öner."},
    {"id": "quant_validator", "kind": "generative",
     "prompt": "Sen nicel doğrulayıcısın. Verilen skorların istatistiksel olarak tutarlı olup olmadığını sorgula, aşırı güveni cezalandır."},
    {"id": "adversarial_stress", "kind": "generative",
     "prompt": "Sen stres testi ajanısın. 'Bu pozisyon şu an ters giderse en kötü senaryo ne olur' diye düşün ve buna göre oy ver."},
]

RESPONSE_INSTR = (
    "Sadece geçerli JSON döndür, başka hiçbir metin ekleme: "
    '{"direction":"LONG|SHORT|FLAT","confidence":0-100,"reason":"kısa gerekçe (max 25 kelime)"}'
)


def _build_prompt(role_prompt: str, symbol: str, snapshot: Dict[str, Any]) -> str:
    return (
        f"{role_prompt}\n"
        f"Sembol: {symbol}\n"
        f"Fiyat: {snapshot.get('price')}\n"
        f"Rejim: {snapshot.get('regime')} (ATR%%={snapshot.get('atr_pct'):.4f})\n"
        f"Teknik skor (−100..+100): {snapshot.get('tech_score'):.2f}\n"
        f"İndikatörler: {json.dumps(snapshot.get('indicators', {}), ensure_ascii=False)}\n"
        f"Zaman dilimi skorları: {json.dumps(snapshot.get('tf_scores', {}), ensure_ascii=False)}\n"
        f"İleri yön projeksiyonu (momentum ekstrapolasyonu, garanti değil): "
        f"{json.dumps(snapshot.get('forward_projection', {}), ensure_ascii=False)}\n"
        f"Osilatör uyuşması (RSI/Stoch/Williams%R/CCI/MFI/Bollinger — çoklu aşırı-bölge tespiti): "
        f"{snapshot.get('reversion_label', '')}\n"
        f"Açık pozisyon sayısı: {snapshot.get('open_positions', 0)}\n\n"
        f"{RESPONSE_INSTR}"
    )


def _parse_vote(text: str) -> Tuple[Optional[str], float, str]:
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        obj = json.loads(text[start:end])
        direction = str(obj.get("direction", "FLAT")).upper()
        if direction not in ("LONG", "SHORT", "FLAT"):
            direction = "FLAT"
        conf = float(obj.get("confidence", 0))
        conf = max(0.0, min(100.0, conf))
        reason = str(obj.get("reason", ""))[:300]
        return direction, conf, reason
    except Exception:
        return None, 0.0, "parse_error"


# --------------------------------------------------------- PROVIDER CALLS --
def _call_openrouter(model: str, prompt: str, api_key: str) -> str:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.25,
        "max_tokens": 120,
    }).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://termux.local/ai-parliament",
        "X-Title": "AI-Parliament",
    }
    data = _http_json(OR_CHAT_URL, headers, body=body, method="POST", timeout=AGENT_TIMEOUT_SEC)
    return data["choices"][0]["message"]["content"]


def _call_gemini(prompt: str, api_key: str, model: str = "gemini-2.0-flash") -> str:
    url = GEMINI_URL_TMPL.format(model=model, key=api_key)
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
    data = _http_json(url, {"Content-Type": "application/json"}, body=body, method="POST", timeout=AGENT_TIMEOUT_SEC)
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _call_xai(prompt: str, api_key: str, model: str = "grok-2-latest") -> str:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.25,
        "max_tokens": 120,
    }).encode("utf-8")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = _http_json(XAI_URL, headers, body=body, method="POST", timeout=AGENT_TIMEOUT_SEC)
    return data["choices"][0]["message"]["content"]


def _call_anthropic(prompt: str, api_key: str, model: str = "claude-sonnet-4-6") -> str:
    body = json.dumps({
        "model": model,
        "max_tokens": 150,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    data = _http_json(ANTHROPIC_URL, headers, body=body, method="POST", timeout=AGENT_TIMEOUT_SEC)
    return data["content"][0]["text"]


@dataclass
class Vote:
    agent_id: str
    model: str
    direction: Optional[str]
    confidence: float
    weight: float
    reason: str
    error: str = ""


@dataclass
class ParliamentResult:
    votes: List[Vote] = field(default_factory=list)
    quorum: int = 0
    direction: Optional[str] = None
    ai_score: float = 0.0          # -100..+100, weight-normalized
    ai_confidence: float = 0.0     # 0..100 ağırlıklı ortalama güven
    reliable: bool = False


SINGLE_MODEL_OVERRIDE = os.getenv("SINGLE_MODEL_OVERRIDE", "").strip()  # "" = normal 20 ajanlı parlamento; doluysa "1 model = 1 motor"
SINGLE_MODEL_QUORUM = int(os.getenv("SINGLE_MODEL_QUORUM", "1"))
HELPER_MODEL_1 = os.getenv("HELPER_MODEL_1", "").strip()  # "1 ana + 2 yardımcı" mini-parlamento için
HELPER_MODEL_2 = os.getenv("HELPER_MODEL_2", "").strip()


def _run_team(symbol: str, snapshot: Dict[str, Any], primary: str, helpers: List[str]) -> ParliamentResult:
    """
    "1 ana + N yardımcı" mini-parlamento: PRIMARY_MODEL o motorun baş
    karar vericisi (ağırlığı 1.5x — "onun imzası"), yardımcı modeller
    (HELPER_MODEL_1/2) ikinci görüş verir, ağırlıkları 1.0x. Tam 20 ajanlı
    parlamentonun küçültülmüş, tek bir modele "sahiplik" veren hali —
    her motorun kendine has, ayrı model kombinasyonuyla çalışmasını sağlar.
    """
    roles = [(primary, "sen bu motorun BAŞ karar vericisisin, nihai sorumluluk sende", 1.5)]
    for h in helpers:
        if h:
            roles.append((h, "sen bu motorun yardımcı analistisin, baş karar vericiye ikinci görüş sun", 1.0))

    votes: List[Vote] = []
    for model, role_desc, weight_mult in roles:
        agent_id = f"team:{model}"
        prompt = _build_prompt(role_desc, symbol, snapshot)
        t0 = time.time()
        try:
            if model == "gemini-native":
                raw = _call_gemini(prompt, os.getenv("GOOGLE_API_KEY", "").strip())
            elif model == "grok-native":
                raw = _call_xai(prompt, os.getenv("XAI_API_KEY", "").strip())
            elif model == "claude-native":
                raw = _call_anthropic(prompt, os.getenv("ANTHROPIC_API_KEY", "").strip())
            else:
                raw = _call_openrouter(model, prompt, os.getenv("OPENROUTER_API_KEY", "").strip())
            direction, conf, reason = _parse_vote(raw)
            if direction is None:
                raise RuntimeError("JSON parse edilemedi: %r" % raw[:120])
            w = get_weight(agent_id) * weight_mult
            latency = int((time.time() - t0) * 1000)
            votes.append(Vote(agent_id, model, direction, conf, w, reason))
            log_vote(symbol, agent_id, model, direction, conf, w, latency, reason)
        except Exception as e:
            latency = int((time.time() - t0) * 1000)
            log_vote(symbol, agent_id, model, None, 0.0, get_weight(agent_id), latency, "", str(e))

    result = ParliamentResult(votes=votes, quorum=len(votes))
    if not votes:
        return result
    long_w = sum(v.weight * v.confidence for v in votes if v.direction == "LONG")
    short_w = sum(v.weight * v.confidence for v in votes if v.direction == "SHORT")
    total_w = sum(v.weight * max(v.confidence, 1.0) for v in votes)
    net = long_w - short_w
    result.ai_score = max(-100.0, min(100.0, (net / total_w) * 100.0)) if total_w > 0 else 0.0
    result.ai_confidence = sum(v.confidence * v.weight for v in votes) / sum(v.weight for v in votes)
    result.direction = "LONG" if result.ai_score > 0 else ("SHORT" if result.ai_score < 0 else "FLAT")
    result.reliable = result.quorum >= SINGLE_MODEL_QUORUM
    return result


def run_parliament(symbol: str, snapshot: Dict[str, Any]) -> ParliamentResult:
    """
    Tüm ajanları sırayla çağırır (Termux/tek çekirdek ortamda thread pool
    yerine art arda çağrı — API rate-limit'lerine karşı daha güvenli).
    Başarısız ajanlar sonuçtan tamamen düşer; sahte oyla doldurulmaz.

    SINGLE_MODEL_OVERRIDE dolu ise (ör. "google/gemini-2.0-flash-exp:free"):
    20 ajanlı parlamento yerine SADECE o tek model karar verir — "1 model
    = 1 motor/araba" mimarisi. Çoklu hesap kurulumunda (setup_multi_account.sh)
    her hesabın .env'ine farklı bir SINGLE_MODEL_OVERRIDE yazarak 10 hesabın
    her birini FARKLI bir AI modeli sürsün diye ayarlayabilirsin.
    """
    if SINGLE_MODEL_OVERRIDE:
        helpers = [h for h in (HELPER_MODEL_1, HELPER_MODEL_2) if h]
        if helpers:
            return _run_team(symbol, snapshot, SINGLE_MODEL_OVERRIDE, helpers)
        return _run_single_model(symbol, snapshot, SINGLE_MODEL_OVERRIDE)

    or_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    gem_key = os.getenv("GOOGLE_API_KEY", "").strip()
    xai_key = os.getenv("XAI_API_KEY", "").strip()
    ant_key = os.getenv("ANTHROPIC_API_KEY", "").strip()

    pool = discover_free_openrouter_models() if or_key else []
    votes: List[Vote] = []

    for i, role in enumerate(AGENT_ROLES):
        prompt = _build_prompt(role["prompt"], symbol, snapshot)
        agent_id = role["id"]
        model_used = ""
        t0 = time.time()
        try:
            if not or_key:
                raise RuntimeError("OPENROUTER_API_KEY yok")
            if not pool:
                raise RuntimeError("ücretsiz model havuzu boş (keşif başarısız)")
            model_used = pool[i % len(pool)]
            raw = _call_openrouter(model_used, prompt, or_key)
            direction, conf, reason = _parse_vote(raw)
            if direction is None:
                raise RuntimeError("JSON parse edilemedi: %r" % raw[:120])
            w = get_weight(agent_id)
            latency = int((time.time() - t0) * 1000)
            votes.append(Vote(agent_id, model_used, direction, conf, w, reason))
            log_vote(symbol, agent_id, model_used, direction, conf, w, latency, reason)
        except Exception as e:
            latency = int((time.time() - t0) * 1000)
            log_vote(symbol, agent_id, model_used, None, 0.0, get_weight(agent_id), latency, "", str(e))

    # Native ekstra ajanlar (varsa) — bunlar sabit rol listesine dahil değil,
    # konseye "ekstra" üye olarak eklenir.
    native_calls = []
    if gem_key:
        native_calls.append(("gemini_native", lambda p: _call_gemini(p, gem_key)))
    if xai_key:
        native_calls.append(("grok_native", lambda p: _call_xai(p, xai_key)))
    if ant_key:
        native_calls.append(("claude_native", lambda p: _call_anthropic(p, ant_key)))

    for agent_id, fn in native_calls:
        prompt = _build_prompt(
            "Sen bağımsız, üçüncü göz bir hakemsin. Diğer ajanlardan habersizsin; kendi analizini yap.",
            symbol, snapshot,
        )
        t0 = time.time()
        try:
            raw = fn(prompt)
            direction, conf, reason = _parse_vote(raw)
            if direction is None:
                raise RuntimeError("JSON parse edilemedi: %r" % raw[:120])
            w = get_weight(agent_id)
            latency = int((time.time() - t0) * 1000)
            votes.append(Vote(agent_id, agent_id, direction, conf, w, reason))
            log_vote(symbol, agent_id, agent_id, direction, conf, w, latency, reason)
        except Exception as e:
            latency = int((time.time() - t0) * 1000)
            log_vote(symbol, agent_id, agent_id, None, 0.0, get_weight(agent_id), latency, "", str(e))

    result = ParliamentResult(votes=votes, quorum=len(votes))
    if not votes:
        return result

    long_w = sum(v.weight * v.confidence for v in votes if v.direction == "LONG")
    short_w = sum(v.weight * v.confidence for v in votes if v.direction == "SHORT")
    total_w = sum(v.weight * max(v.confidence, 1.0) for v in votes)
    net = long_w - short_w
    result.ai_score = max(-100.0, min(100.0, (net / total_w) * 100.0)) if total_w > 0 else 0.0
    result.ai_confidence = sum(v.confidence * v.weight for v in votes) / sum(v.weight for v in votes) if votes else 0.0
    result.direction = "LONG" if result.ai_score > 0 else ("SHORT" if result.ai_score < 0 else "FLAT")
    result.reliable = result.quorum >= MIN_QUORUM
    return result


def generate_improvement_suggestion(performance_summary: Dict[str, Any]) -> Optional[str]:
    """
    Tek bir AI ajanına son performans özetini gösterip DÜZ METİN bir
    öneri istenir (kod değil, parametre önerisi). Bu öneri HİÇBİR ZAMAN
    otomatik uygulanmaz — sadece panelde "bilgi amaçlı" gösterilir, canlı
    sisteme etki etmeden. Gerçek "üretken AI platformu geliştiriyor"
    isteğinin güvenli karşılığı budur: fikir üretir, karar ve uygulama
    her zaman insanda kalır.
    """
    or_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not or_key:
        return None
    pool = discover_free_openrouter_models()
    if not pool:
        return None
    prompt = (
        "Sen bir kantitatif strateji danışmanısın. Aşağıdaki performans özetine bakıp "
        "SADECE TEK BİR somut, ölçülebilir parametre önerisi ver (ör. 'MIN_FINAL_CONF eşiğini "
        "5 puan artır çünkü düşük güvenli işlemler zarar ediyor'). Kod ÖNERME, sadece "
        "parametre/strateji önerisi. Türkçe, en fazla 40 kelime, düz metin.\n\n"
        f"Performans özeti: {json.dumps(performance_summary, ensure_ascii=False)}"
    )
    try:
        raw = _call_openrouter(pool[0], prompt, or_key)
        return raw.strip()[:400]
    except Exception:
        return None


def _run_single_model(symbol: str, snapshot: Dict[str, Any], model: str) -> ParliamentResult:
    """"1 model = 1 motor" modu: 20 ajan yerine SADECE bu tek model çağrılır.
    OpenRouter model ID'siyse OPENROUTER_API_KEY kullanılır; "gemini-native",
    "grok-native", "claude-native" yazılırsa ilgili native API kullanılır."""
    agent_id = f"single:{model}"
    prompt = _build_prompt(
        "Sen bu motorun TEK karar vericisisin. Diğer ajanlardan bağımsız, kendi analizinle karar ver.",
        symbol, snapshot,
    )
    t0 = time.time()
    votes: List[Vote] = []
    try:
        if model == "gemini-native":
            raw = _call_gemini(prompt, os.getenv("GOOGLE_API_KEY", "").strip())
        elif model == "grok-native":
            raw = _call_xai(prompt, os.getenv("XAI_API_KEY", "").strip())
        elif model == "claude-native":
            raw = _call_anthropic(prompt, os.getenv("ANTHROPIC_API_KEY", "").strip())
        else:
            raw = _call_openrouter(model, prompt, os.getenv("OPENROUTER_API_KEY", "").strip())
        direction, conf, reason = _parse_vote(raw)
        if direction is None:
            raise RuntimeError("JSON parse edilemedi: %r" % raw[:120])
        w = get_weight(agent_id)
        latency = int((time.time() - t0) * 1000)
        votes.append(Vote(agent_id, model, direction, conf, w, reason))
        log_vote(symbol, agent_id, model, direction, conf, w, latency, reason)
    except Exception as e:
        latency = int((time.time() - t0) * 1000)
        log_vote(symbol, agent_id, model, None, 0.0, get_weight(agent_id), latency, "", str(e))

    result = ParliamentResult(votes=votes, quorum=len(votes))
    if not votes:
        return result
    v = votes[0]
    result.ai_score = v.confidence if v.direction == "LONG" else (-v.confidence if v.direction == "SHORT" else 0.0)
    result.ai_confidence = v.confidence
    result.direction = v.direction
    result.reliable = result.quorum >= SINGLE_MODEL_QUORUM
    return result


def settle_round(votes: List[Vote], actual_direction_was_profitable: Dict[str, bool]) -> None:
    """
    Bir pozisyon kapandığında çağrılır: actual_direction_was_profitable =
    {"LONG": True/False, "SHORT": True/False} — o yönde işlem açılsaydı
    kâr mı zarar mı ederdi. Her ajanın kendi yön tahminine göre ağırlığı
    güncellenir (dinamik skorlama).
    """
    for v in votes:
        if v.direction in ("LONG", "SHORT") and v.direction in actual_direction_was_profitable:
            update_weight(v.agent_id, actual_direction_was_profitable[v.direction])
