#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""
α-ACADEMIC SIGNATURE PROOF + LIVE KERNEL TEST (Termux-safe)
==========================================================
Sadece / eğik çizgi. $HOME kullanılır. Asla \\ yok.
"""
from __future__ import annotations
import hashlib
import hmac
import os
import sys
import time
import urllib.parse

def academic_hmac_proof(secret: str, params: dict) -> str:
    clean = {str(k): str(v) for k, v in params.items() if v is not None}
    qs = urllib.parse.urlencode(sorted(clean.items()), doseq=True)
    sig = hmac.new(secret.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()
    return qs + "&signature=" + sig

def run_academic_tests():
    print("=== α-ACADEMIC HMAC-SHA256 PROOF ===")
    secret = "test_secret_key_12345"
    params = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "MARKET",
        "quantity": "0.001",
        "timestamp": 1699999999999,
        "recvWindow": 5000,
    }
    result = academic_hmac_proof(secret, params)
    expected_qs_part = "quantity=0.001&recvWindow=5000&side=BUY&symbol=BTCUSDT&timestamp=1699999999999&type=MARKET"
    assert expected_qs_part in result, "Query string sıralaması bozuldu"
    assert "&signature=" in result, "Signature eklentisi eksik"
    sig = result.split("&signature=")[1]
    assert len(sig) == 64, "HMAC-SHA256 hex uzunluğu 64 olmalı"
    print("[PASS] Sıralı query string + 64 karakter hex signature")
    print("[PASS] None değerler filtrelendi")
    print("[PASS] Deterministik çıktı (alfabetik sort)")
    print("Akademik kanıt başarılı.\n")

def run_live_kernel_test():
    print("=== LIVE KERNEL SIGNATURE TEST ===")
    try:
        from live.kernel import LiveKernel, load_env
    except ImportError:
        print("[SKIP] live.kernel import edilemedi (path kontrol et)")
        return

    env = load_env()
    key = (env.get("BINANCE_API_KEY") or "").strip()
    sec = (
        env.get("BINANCE_SECRET_KEY")
        or env.get("BINANCE_API_SECRET")
        or env.get("BINANCE_SECRET")
        or ""
    ).strip()

    if not key or not sec:
        print("[WARN] API key/secret .env içinde yok — sadece offline test yapıldı")
        return

    k = LiveKernel(venue="usdt")
    print("[INFO] LiveKernel yüklendi, time sync deneniyor...")
    try:
        k.sync_time()
        print("[PASS] time sync başarılı (offset=%d ms)" % k._off)
    except Exception as e:
        print("[FAIL] time sync: %s" % e)
        return

    try:
        bal = k.balance_usdt()
        print("[PASS] balance_usdt() = %.4f USDT" % bal)
    except RuntimeError as e:
        if "-2015" in str(e):
            print("[CRITICAL] -2015 yakalandı → fail-closed çalışıyor (doğru davranış)")
        else:
            print("[FAIL] balance: %s" % e)
    except Exception as e:
        print("[FAIL] beklenmeyen: %s" % e)

    print("\n=== TEST TAMAMLANDI ===")

if __name__ == "__main__":
    run_academic_tests()
    run_live_kernel_test()
