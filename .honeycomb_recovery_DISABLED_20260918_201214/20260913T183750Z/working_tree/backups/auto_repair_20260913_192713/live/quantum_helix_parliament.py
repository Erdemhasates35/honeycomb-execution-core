#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
MODULE: QUANTUM HELIX PARLIAMENT (Production Integration)
CORE: Softmax Probability Distribution, Shannon Entropy Filtering,
      SHA-3/512 Consensus Sealing & OpenRouter Live Parliament Integration.
===============================================================================
"""

import json
import time
import hashlib
import numpy as np
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional

class QuantumProbabilityEngine:
    """
    Softmax tabanlı Kuantum Olasılık Dağılımı ve Entropi Arıtım Katmanı.
    """
    @staticmethod
    def compute_softmax(scores: List[float]) -> np.ndarray:
        if not scores:
            return np.array([])
        arr = np.array(scores, dtype=np.float64)
        # Numerik kararlılık için max çıkarılır (overflow koruması)
        shift_arr = arr - np.max(arr)
        exps = np.exp(shift_arr)
        return exps / np.sum(exps)

    @staticmethod
    def evaluate_votes(agent_votes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Ajan oylarını ve güven skorlarını kuantum olasılık dağılımı ile analiz eder.
        """
        if not agent_votes:
            return {"consensus": "FLAT", "confidence": 0.0, "entropy": 0.0, "status": "NO_VOTES"}

        # Veto kontrolü
        if any(v.get("veto", False) for v in agent_votes):
            return {"consensus": "FLAT", "confidence": 0.0, "entropy": 0.0, "status": "GENERATIVE_VETO"}

        # Yön ağırlıkları
        long_conf = [v["confidence"] for v in agent_votes if v["side"] == "LONG"]
        short_conf = [v["confidence"] for v in agent_votes if v["side"] == "SHORT"]
        flat_conf = [v["confidence"] for v in agent_votes if v["side"] == "FLAT"]

        sum_long = sum(long_conf)
        sum_short = sum(short_conf)
        sum_flat = sum(flat_conf) if flat_conf else 1e-6

        raw_vector = [sum_long, sum_short, sum_flat]
        probabilities = QuantumProbabilityEngine.compute_softmax(raw_vector)

        # Shannon Entropi Hesabı: H(P) = -sum(P * log2(P))
        entropy = -float(np.sum(probabilities * np.log2(probabilities + 1e-12)))

        p_long, p_short, p_flat = probabilities[0], probabilities[1], probabilities[2]

        # Karar Mekanizması
        if p_long > p_short and p_long > p_flat and p_long >= 0.45:
            consensus = "LONG"
            confidence = float(p_long * 100)
        elif p_short > p_long and p_short > p_flat and p_short >= 0.45:
            consensus = "SHORT"
            confidence = float(p_short * 100)
        else:
            consensus = "FLAT"
            confidence = float(max(p_long, p_short, p_flat) * 100)

        # Entropi Filtresi: Kararsızlık yüksekse (Entropi > 1.2) pozisyona girme
        if entropy > 1.25 and consensus != "FLAT":
            return {
                "consensus": "FLAT",
                "confidence": confidence,
                "entropy": round(entropy, 4),
                "status": "ENTROPY_TOO_HIGH_REJECTED"
            }

        return {
            "consensus": consensus,
            "confidence": round(confidence, 2),
            "entropy": round(entropy, 4),
            "probabilities": {
                "LONG": round(float(p_long), 4),
                "SHORT": round(float(p_short), 4),
                "FLAT": round(float(p_flat), 4)
            },
            "status": "APPROVED"
        }


class SHA3ConsensusSealer:
    """
    Ajan oylamalarını ve kararları SHA-3/512 ile mühürleyen kriptografik bloklayıcı.
    """
    def __init__(self, node_id: str = "HELIX-PARLIAMENT-NODE"):
        self.node_id = node_id

    def create_seal(self, symbol: str, tech_data: Dict[str, Any], vote_result: Dict[str, Any], raw_votes: List[Dict]) -> Dict[str, Any]:
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        payload = {
            "symbol": symbol,
            "tech": tech_data,
            "result": vote_result,
            "votes": raw_votes
        }
        
        payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        hash_input = f"{self.node_id}:{timestamp}:{payload_bytes.hex()}"
        consensus_hash = hashlib.sha3_512(hash_input.encode("utf-8")).hexdigest()

        return {
            "timestamp": timestamp,
            "symbol": symbol,
            "consensus_hash": consensus_hash,
            "payload": payload,
            "status": "SEALED_ABSOLUTE_TRUTH"
        }


def quantum_parliament_vote_integration(
    symbol: str, 
    tech: Dict[str, Any], 
    raw_votes_from_openrouter: List[Dict[str, Any]],
    sealer: SHA3ConsensusSealer
) -> Tuple[Optional[str], float, Dict[str, Any]]:
    """
    Helix Sovereign Pro için güncellenmiş parlamento entegrasyon fonksiyonu.
    """
    # 1. Softmax ve Entropi Analizi
    evaluation = QuantumProbabilityEngine.evaluate_votes(raw_votes_from_openrouter)
    consensus_side = evaluation["consensus"]
    confidence = evaluation["confidence"]

    if evaluation["status"] != "APPROVED":
        consensus_side = None

    # 2. SHA-3/512 Kriptografik Mühürleme
    seal_block = sealer.create_seal(symbol, tech, evaluation, raw_votes_from_openrouter)

    return consensus_side, confidence, seal_block


# --- CANLI ENTEGRASYON DOĞRULAMA VE TEST ÇALIŞTIRMASI ---
if __name__ == "__main__":
    print("=" * 70)
    print("🚀 QUANTUM HELIX PARLIAMENT INTEGRATION CORE ACTIVATED")
    print("=" * 70)

    # Örnek Gerçekçi Ajan Oyları
    sample_votes = [
        {"id": "fin_alpha", "role": "financial", "side": "LONG", "confidence": 85.0, "veto": False},
        {"id": "fin_beta", "role": "financial", "side": "LONG", "confidence": 78.0, "veto": False},
        {"id": "gen_coord", "role": "generative", "side": "LONG", "confidence": 90.0, "veto": False},
        {"id": "gen_risk", "role": "generative", "side": "FLAT", "confidence": 40.0, "veto": False}
    ]

    sample_tech = {"symbol": "BTCUSDT", "price": 92450.0, "rsi": 58.2, "trend": "UP", "score": 68.0}
    
    sealer = SHA3ConsensusSealer()
    side, conf, seal = quantum_parliament_vote_integration("BTCUSDT", sample_tech, sample_votes, sealer)

    print(f"\n[Sonuç Kararı] Yön: {side} | Güven: %{conf}")
    print(f"[Entropi Skoru] {seal['payload']['result']['entropy']}")
    print(f"[Softmax Olasılıkları] {seal['payload']['result']['probabilities']}")
    print(f"[SHA-3/512 Mühür Hash]:\n{seal['consensus_hash']}")
    print("=" * 70)
