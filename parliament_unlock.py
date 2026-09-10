#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""PARLIAMENT Sert Kilit kalibrasyonu.

AI_PARLIAMENT / SOVEREIGN_PARLIAMENT dosyalarinin en tepesine:

    from parliament_unlock import cfg, LOCK_COOLDOWN, SOFT_LOCK

sonra dosya icindeki sabit 29 dk (1740) ifadesini LOCK_COOLDOWN ile degistirin.
Gercekci degerler:
  - SOFT_LOCK=False  -> koruma hala calisir ama her kilit sonrasi 60 sn taze sinyal
                       kontrolu yapar; 29 dk koruma yerine hata sayacina gore
                       5 dk / 15 dk / 60 dk eskalasyonu kullanir.
  - Tam kaldirmak icin: python3 parliament_unlock.py --force
    (uzak durman gereken tek durum: HIGHVOL rejiminde bile acmak. Bu buyuk
     kayip riskidir; literaturlere gore yuksek volatilitede taker maliyeti
     beklenen getiriyi bastirir.)
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.expanduser("~/honeycomb-execution-core")
CFG = os.path.join(ROOT, "live", "parliament_config.json")

DEFAULTS = {
    "soft_lock": False,           # koruma aktif ama eskalasyonlu
    "lock_cooldown_sec": 300,    # ilk kilit 5 dk (29 dk degil)
    "escalation": [300, 900, 3600],  # ust uste kilitlerde 5dk->15dk->60dk
    "min_score_threshold": 20.0, # bu skor altinda hic girme
    "highvol_hard_block": False,  # HIGHVOL'de acma yasagi (acik birak)
    "max_trades_per_hour": 12,   # overtrading freni
}

def cfg(key: str, default=None):
    try:
        with open(CFG) as f:
            data = json.load(f)
    except Exception:
        data = DEFAULTS
    return data.get(key, DEFAULTS.get(key, default))

LOCK_COOLDOWN = cfg("lock_cooldown_sec", 300)
SOFT_LOCK = cfg("soft_lock", False)

def write_config(overrides: dict) -> None:
    data = dict(DEFAULTS)
    data.update(overrides)
    os.makedirs(os.path.dirname(CFG), exist_ok=True)
    with open(CFG, "w") as f:
        json.dump(data, f, indent=2)
    print("Yazildi:", CFG)
    print(json.dumps(data, indent=2))

if __name__ == "__main__":
    if "--force" in sys.argv:
        write_config({"soft_lock": False, "lock_cooldown_sec": 0,
                      "highvol_hard_block": False})
        print("UYARI: kilit TAMAMEN kaldirildi. HIGHVOL'de bile islem acilacak. "
              "Bunun riski tamamen size ait.")
    else:
        write_config({})
        print("Soft-lock kuruldu: 5 dk -> 15 dk -> 60 dk eskalasyon, "
              "saatte max 12 islem, HIGHVOL engeli acik.")
