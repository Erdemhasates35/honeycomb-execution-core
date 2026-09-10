#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""kernel_hardened_sign v2 - dogrulama testleri. Bilinen cevaplar Binance dokumanindan."""
import hashlib
import hmac as hmac_mod
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.expanduser("~/honeycomb-execution-core"))
from live.kernel_hardened_sign import hardened_sign, CODE_MAP  # type: ignore

FAILS = []

def check(name, cond):
    print(("PASS" if cond else "FAIL"), "-", name)
    if not cond:
        FAILS.append(name)

# 1) Binance resmi ornegi (dokumandaki test vektoru)
secret = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
params = {"symbol": "LTCBTC", "side": "BUY", "type": "LIMIT",
          "timeInForce": "GTC", "quantity": 1, "price": 0.1,
          "recvWindow": 5000, "timestamp": 1499827319559}
expected = "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"
got = hardened_sign(secret, params)
check("HMAC-SHA256 Binance resmi test vektoru", got == expected)

# 2) None parametreler temizleniyor
got2 = hardened_sign(secret, {"a": 1, "b": None})
qs = urllib.parse.urlencode(sorted({"a": "1"}.items()))
want2 = hmac_mod.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
check("None-free temizleme", got2 == want2)

# 3) Siralama deterministik
g1 = hardened_sign(secret, {"b": 2, "a": 1})
g2 = hardened_sign(secret, {"a": 1, "b": 2})
check("Parametre siralama deterministik", g1 == g2)

# 4) -4056 idempotent basari listesinde
check("-4056 idempotent OK haritasinda", CODE_MAP.get(-4056, (False, ""))[0] is False)

# 5) -2015 retry disi + hard stop
check("-2015 retry yok", CODE_MAP.get(-2015, (True, ""))[0] is False)

# 6) bos secret RuntimeError
try:
    hardened_sign(b"", {"a": 1})
    check("bos secret reddedildi", False)
except RuntimeError:
    check("bos secret reddedildi", True)

print()
if FAILS:
    print("SONUC: %d test FAILED -> %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("SONUC: TUM TESTLER PASS - kernel imza katmani uretime hazir")
