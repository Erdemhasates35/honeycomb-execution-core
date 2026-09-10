#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
from dataclasses import dataclass

@dataclass
class TradeEconomics:
    """
    [PALEO PRENSİBİ CANLI KART METRİKLERİ]
    engine_percentage_adapter.py dosyasının okuduğu tüm 11 veri alanı
    tip ihlali olmaksızın tam deterministik standartta tanımlanmıştır.
    """
    n: int = 0
    win_probability_pct: float = 0.0
    loss_probability_pct: float = 0.0
    avg_gross_win_pct: float = 0.0
    avg_gross_loss_pct: float = 0.0
    avg_total_cost_pct: float = 0.0
    avg_net_win_pct: float = 0.0
    avg_net_loss_pct: float = 0.0
    expected_net_pct: float = 0.0
    profit_factor: float = 0.0
    break_even_win_probability_pct: float = 0.0
    edge_cost_ratio: float = 0.0


def approval(stats: TradeEconomics) -> bool:
    """
    PALEO MATEMATİKSEL ONAY FİLTRESİ:
    Sistemde yapay varsayım veya halüsinasyona yer yoktur.
    Bir stratejinin canlı emre dönüşebilmesi için 3 temel şart aranır:
    1. Örneklem büyüklüğü (n) sıfırdan büyük olmalıdır.
    2. Beklenen net getiri (expected_net_pct) pozitif olmalıdır.
    3. Kazanma olasılığı, başabaş (break-even) sınırından yüksek olmalıdır.
    """
    if stats.n <= 0:
        return False
        
    if stats.expected_net_pct <= 0.0:
        return False

    if stats.profit_factor <= 1.0:
        return False

    if stats.win_probability_pct <= stats.break_even_win_probability_pct:
        return False

    return True
