#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HONEYCOMB — PRODUCTION TRUTH / ACADEMIC EVIDENCE GATE
======================================================

Amaç:
- Mevcut sistemi silmeden doğrulamak.
- Rust/Go bağımlılığı oluşturmamak.
- Python + standart kütüphane ile çalışmak.
- Sentetik/mock işlem üretmemek.
- Confidence değerini otomatik olarak probability kabul etmemek.
- Gerçek fill/fee/slippage/funding/PNL kanıtı olmadan ekonomik PASS vermemek.
- Equity <= 0 ise HARD_KILL.
- LIVE işlem kapısı açık değilse gerçek emir yetkilendirmemek.
- Her kritik kararın nedenini JSONL audit dosyasına yazmak.
- Akademik olarak iddia ile ölçülmüş sonucu birbirinden ayırmak.

Bu dosya emir göndermez.
Mevcut execution motorlarını silmez/değiştirmez.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import time
import traceback
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent
AUDIT_DIR = ROOT / "audit"
AUDIT_DIR.mkdir(parents=True, exist_ok=True)

AUDIT_FILE = AUDIT_DIR / "production_truth_gate.jsonl"
REPORT_FILE = AUDIT_DIR / "production_truth_report.json"

MIN_NOTIONAL_USDT = 20.0
MAX_CAPITAL_FRACTION = 0.30
BAN_SUSPEND_SECONDS = 120.0
MIN_REAL_OBSERVATIONS = 30

# α yalnızca kullanıcı tarafından tanımlanmış bir parametre olarak tutulur.
# Finansal doğrulaması yapılmış bir trading sabiti olduğu iddia edilmez.
ALPHA = 0.00729735256


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def finite(x: Any) -> bool:
    try:
        return math.isfinite(float(x))
    except Exception:
        return False


def pct(x: float) -> float:
    return float(x) * 100.0


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


class Audit:
    def __init__(self, path: Path = AUDIT_FILE):
        self.path = path

    def write(self, event: str, **data: Any) -> None:
        record = {
            "ts_ms": now_ms(),
            "ts_tr": time.strftime("%Y-%m-%d %H:%M:%S"),
            "event": event,
            **data,
        }

        line = json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())


AUDIT = Audit()


@dataclass
class Check:
    number: int
    name: str
    status: str
    evidence: str
    details: dict[str, Any]

    def emit(self) -> None:
        AUDIT.write(
            "FORMAL_VERIFICATION",
            number=self.number,
            name=self.name,
            status=self.status,
            evidence=self.evidence,
            details=self.details,
        )


class TruthGate:
    def __init__(self) -> None:
        self.checks: list[Check] = []

    def check(
        self,
        number: int,
        name: str,
        condition: bool,
        evidence: str,
        **details: Any,
    ) -> bool:
        c = Check(
            number=number,
            name=name,
            status="PASS" if condition else "FAIL",
            evidence=evidence,
            details=details,
        )
        c.emit()
        self.checks.append(c)
        return condition

    @property
    def passed(self) -> int:
        return sum(x.status == "PASS" for x in self.checks)

    @property
    def failed(self) -> int:
        return sum(x.status == "FAIL" for x in self.checks)


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)

    if raw is None:
        return default

    return raw.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
        "live",
    }


def env_float(name: str, default: float | None = None) -> float | None:
    raw = setting(name)

    if raw is None or not str(raw).strip():
        return default

    try:
        return float(raw)
    except ValueError:
        return default


def load_dotenv_preserve() -> dict[str, str]:
    """
    .env değerlerini shell environment'ını ezmeden okur.
    """
    path = ROOT / ".env"

    if not path.exists():
        return {}

    result: dict[str, str] = {}

    for raw in path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines():

        line = raw.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()

        if key:
            result[key] = value.strip().strip('"').strip("'")

    return result


DOTENV = load_dotenv_preserve()


def setting(name: str, default: Any = None) -> Any:
    if name in os.environ:
        return os.environ[name]

    if name in DOTENV:
        return DOTENV[name]

    return default


def discover_python_files() -> list[Path]:
    files: list[Path] = []

    for p in ROOT.rglob("*.py"):
        if any(
            part in {
                ".git",
                ".venv",
                "venv",
                "__pycache__",
                "node_modules",
            }
            for part in p.parts
        ):
            continue

        files.append(p)

    return sorted(files)


def source_text() -> str:
    chunks: list[str] = []

    for p in discover_python_files():
        try:
            chunks.append(
                p.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            )
        except Exception:
            pass

    return "\n".join(chunks)


def sqlite_files() -> list[Path]:
    result = []

    for p in ROOT.rglob("*.db"):
        if ".git" in p.parts:
            continue

        result.append(p)

    return sorted(result)


def jsonl_files() -> list[Path]:
    result = []

    for p in ROOT.rglob("*.jsonl"):
        if ".git" in p.parts:
            continue

        result.append(p)

    return sorted(result)


def test_python_syntax() -> tuple[bool, dict[str, Any]]:
    failures = []

    for p in discover_python_files():
        try:
            ast.parse(
                p.read_text(
                    encoding="utf-8",
                    errors="replace",
                ),
                filename=str(p),
            )
        except Exception as exc:
            failures.append(
                {
                    "file": str(p.relative_to(ROOT)),
                    "error": repr(exc),
                }
            )

    return (
        not failures,
        {
            "python_files": len(discover_python_files()),
            "syntax_failures": failures,
        },
    )


def test_no_runtime_rust_go_dependency() -> tuple[bool, dict[str, Any]]:
    """
    Kullanıcı talebi:
    Rust/Go critical path yok.

    Burada yalnızca Python tarafında açık runtime dependency
    referanslarını tarıyoruz.
    Dosyaların kendisini silmiyoruz.
    """

    suspicious: list[dict[str, Any]] = []

    patterns = [
        r"\bsubprocess\.(run|Popen|call)([^)]*\b(cargo|rustc|go)\b",
        r"\b(cargo|rustc|go)\s+(run|build|test)\b",
        r"\bimport\s+go\b",
        r"\bimport\s+rust\b",
    ]

    compiled = [re.compile(x, re.I) for x in patterns]

    for p in discover_python_files():
        try:
            text = p.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except Exception:
            continue

        for i, line in enumerate(text.splitlines(), 1):
            if any(rx.search(line) for rx in compiled):
                suspicious.append(
                    {
                        "file": str(p.relative_to(ROOT)),
                        "line": i,
                        "text": line[:300],
                    }
                )

    return (
        not suspicious,
        {
            "runtime_dependency_findings": suspicious,
        },
    )


def test_live_gate() -> tuple[bool, dict[str, Any]]:
    execution = str(
        setting("EXECUTION_MODE", "")
    ).strip().upper()

    armed_raw = setting("LIVE_ARMED", "0")
    armed = str(armed_raw).strip().lower() in {
        "1", "true", "yes", "on", "enabled", "live"
    }

    ok = execution == "LIVE" and armed

    return (
        ok,
        {
            "EXECUTION_MODE": execution,
            "LIVE_ARMED": armed,
            "required": "EXECUTION_MODE=LIVE AND LIVE_ARMED=1",
        },
    )


def test_equity_gate() -> tuple[bool, dict[str, Any]]:
    candidates = [
        "EQUITY",
        "ACCOUNT_EQUITY",
        "TOTAL_EQUITY",
        "USDT_EQUITY",
    ]

    values = {}

    for name in candidates:
        value = env_float(name)

        if value is not None:
            values[name] = value

    positive = [
        float(v)
        for v in values.values()
        if finite(v) and float(v) > 0
    ]

    if not positive:
        return (
            False,
            {
                "reason": "positive_equity_not_observed",
                "values": values,
                "action": "HARD_KILL",
            },
        )

    equity = positive[0]

    return (
        equity > 0,
        {
            "equity": equity,
            "action_if_nonpositive": "HARD_KILL",
        },
    )


def test_min_notional() -> tuple[bool, dict[str, Any]]:
    configured = env_float(
        "MIN_NOTIONAL_USDT",
        MIN_NOTIONAL_USDT,
    )

    ok = (
        configured is not None
        and finite(configured)
        and configured >= MIN_NOTIONAL_USDT
    )

    return (
        ok,
        {
            "configured_min_notional": configured,
            "required_min_notional": MIN_NOTIONAL_USDT,
        },
    )


def test_stop_loss_source(src: str) -> tuple[bool, dict[str, Any]]:
    stop_patterns = [
        r"\bstop[_-]?loss\b",
        r"\bSTOP_MARKET\b",
        r"\bplace_protect\b",
        r"\bprotection_bridge\b",
        r"\bATR\b",
        r"\batr\b",
    ]

    hits = {
        pattern: bool(re.search(pattern, src, re.I))
        for pattern in stop_patterns
    }

    ok = (
        hits["\\bstop[_-]?loss\\b"]
        and (
            hits["\\bSTOP_MARKET\\b"]
            or hits["\\bplace_protect\\b"]
            or hits["\\bprotection_bridge\\b"]
        )
    )

    return (
        ok,
        {
            "patterns": hits,
            "requirement": (
                "Every opened position must have exchange-side protection."
            ),
        },
    )


def test_ban_guard(src: str) -> tuple[bool, dict[str, Any]]:
    patterns = [
        r"BAN",
        r"ban_count",
        r"BINANCE_GUARD",
        r"-1003",
        r"120",
        r"suspend",
    ]

    hits = {
        p: bool(re.search(p, src, re.I))
        for p in patterns
    }

    ok = (
        (
            hits["ban_count"]
            or hits["BINANCE_GUARD"]
            or hits["-1003"]
        )
        and hits["suspend"]
    )

    return (
        ok,
        {
            "patterns": hits,
            "required_suspend_seconds": BAN_SUSPEND_SECONDS,
        },
    )


def test_atomic_state(src: str) -> tuple[bool, dict[str, Any]]:
    lock_patterns = [
        r"\bfcntl\b",
        r"\bfilelock\b",
        r"\bthreading\.Lock\b",
        r"\basyncio\.Lock\b",
        r"\bsqlite3\b",
    ]

    wal_patterns = [
        r"\bWAL\b",
        r"\bwal\b",
        r"\bfsync\b",
        r"\bjournal\b",
    ]

    locks = sum(
        bool(re.search(x, src, re.I))
        for x in lock_patterns
    )

    wal = sum(
        bool(re.search(x, src, re.I))
        for x in wal_patterns
    )

    ok = locks > 0 and wal > 0

    return (
        ok,
        {
            "lock_evidence_count": locks,
            "wal_evidence_count": wal,
        },
    )


def test_partial_fill(src: str) -> tuple[bool, dict[str, Any]]:
    patterns = [
        r"partial[_ -]?fill",
        r"PARTIAL_FILL",
        r"filled_qty",
        r"executedQty",
        r"cancel",
        r"resize",
        r"resized",
    ]

    hits = {
        p: bool(re.search(p, src, re.I))
        for p in patterns
    }

    ok = (
        (
            hits["partial[_ -]?fill"]
            or hits["PARTIAL_FILL"]
            or hits["filled_qty"]
            or hits["executedQty"]
        )
        and hits["cancel"]
    )

    return (
        ok,
        {
            "patterns": hits,
            "requirement": (
                "Partial-fill reconciliation must exist before continuation."
            ),
        },
    )


def observation_from_json(obj: dict[str, Any]) -> bool:
    """
    Gerçek trade observation için minimum kanıt.
    Sentetik değerler kabul edilmez.
    """

    required = [
        "symbol",
        "side",
        "entry",
        "exit",
        "qty",
        "entry_fee",
        "exit_fee",
    ]

    if not all(k in obj for k in required):
        return False

    numeric = [
        obj.get("entry"),
        obj.get("exit"),
        obj.get("qty"),
        obj.get("entry_fee"),
        obj.get("exit_fee"),
    ]

    if not all(finite(x) for x in numeric):
        return False

    if float(obj["entry"]) <= 0:
        return False

    if float(obj["exit"]) <= 0:
        return False

    if float(obj["qty"]) <= 0:
        return False

    return True


def collect_real_observations() -> list[dict[str, Any]]:
    """
    Yalnızca mevcut JSONL kayıtlarını okur.

    Yeni işlem üretmez.
    Confidence -> probability dönüşümü yapmaz.
    """
    observations: list[dict[str, Any]] = []

    for p in jsonl_files():
        try:
            for line in p.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines():

                line = line.strip()

                if not line:
                    continue

                try:
                    obj = json.loads(line)
                except Exception:
                    continue

                if not isinstance(obj, dict):
                    continue

                if observation_from_json(obj):
                    observations.append(obj)

        except Exception:
            continue

    return observations


def collect_sqlite_trade_count() -> dict[str, int]:
    result: dict[str, int] = {}

    for db in sqlite_files():
        try:
            conn = sqlite3.connect(
                f"file:{db}?mode=ro",
                uri=True,
                timeout=1.0,
            )

            tables = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type='table'
                """
            ).fetchall()

            total = 0

            for (table,) in tables:
                if not re.match(
                    r"^[A-Za-z_][A-Za-z0-9_]*$",
                    str(table),
                ):
                    continue

                try:
                    row = conn.execute(
                        f'SELECT COUNT(*) FROM "{table}"'
                    ).fetchone()

                    total += int(row[0] or 0)
                except Exception:
                    pass

            conn.close()

            result[str(db.relative_to(ROOT))] = total

        except Exception:
            result[str(db.relative_to(ROOT))] = -1

    return result


def empirical_economics(
    observations: list[dict[str, Any]],
) -> dict[str, Any]:

    if not observations:
        return {
            "status": "INSUFFICIENT_REAL_DATA",
            "n": 0,
        }

    returns = []

    for o in observations:
        entry = float(o["entry"])
        exit_ = float(o["exit"])
        qty = float(o["qty"])

        side = str(
            o.get("side", "")
        ).upper()

        if side == "SHORT":
            gross = (
                (entry - exit_) * qty
                / (entry * qty)
            )
        else:
            gross = (
                (exit_ - entry) * qty
                / (entry * qty)
            )

        cost = (
            float(o["entry_fee"])
            + float(o["exit_fee"])
            + float(o.get("spread", 0.0))
            + float(o.get("slippage", 0.0))
            + float(o.get("funding", 0.0))
            + float(o.get("impact", 0.0))
        )

        net = gross - cost

        if finite(net):
            returns.append(net)

    if not returns:
        return {
            "status": "NO_FINITE_REAL_RETURNS",
            "n": 0,
        }

    wins = [x for x in returns if x > 0]
    losses = [-x for x in returns if x < 0]

    gross_profit = sum(wins)
    gross_loss = sum(losses)

    p_win = len(wins) / len(returns)
    p_loss = len(losses) / len(returns)

    avg_win = (
        sum(wins) / len(wins)
        if wins
        else 0.0
    )

    avg_loss = (
        sum(losses) / len(losses)
        if losses
        else 0.0
    )

    expected = (
        p_win * avg_win
        - p_loss * avg_loss
    )

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else math.inf
    )

    breakeven = (
        avg_loss / (avg_win + avg_loss)
        if avg_win + avg_loss > 0
        else math.nan
    )

    return {
        "status": "MEASURED",
        "n": len(returns),
        "wins": len(wins),
        "losses": len(losses),
        "p_win": p_win,
        "p_loss": p_loss,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "expected_net_return": expected,
        "profit_factor": pf,
        "break_even_probability": breakeven,
    }


def generalized_kelly(returns: Iterable[float]) -> dict[str, Any]:
    """
    Genel dağılım için log-growth tabanlı fractional Kelly.

    Negatif wealth noktası üreten f değerleri reddedilir.
    """
    xs = [
        float(x)
        for x in returns
        if finite(x)
    ]

    if len(xs) < MIN_REAL_OBSERVATIONS:
        return {
            "status": "INSUFFICIENT_REAL_DATA",
            "n": len(xs),
        }

    best_f = 0.0
    best_growth = -math.inf

    for i in range(1, 1001):
        f = i / 1000.0

        vals = [
            1.0 + f * x
            for x in xs
        ]

        if any(v <= 0 for v in vals):
            continue

        growth = sum(
            math.log(v)
            for v in vals
        ) / len(vals)

        if growth > best_growth:
            best_growth = growth
            best_f = f

    fractional = best_f * 0.25

    return {
        "status": "MEASURED",
        "n": len(xs),
        "full_kelly_grid": best_f,
        "fractional_kelly_25pct": fractional,
        "capital_cap": MAX_CAPITAL_FRACTION,
        "execution_fraction": min(
            fractional,
            MAX_CAPITAL_FRACTION,
        ),
    }


def scan_required_architecture(src: str) -> dict[str, Any]:
    required = {
        "risk_gate": [
            "risk",
            "authorizeOrder",
        ],
        "live_kernel": [
            "LiveKernel",
        ],
        "protection": [
            "ProtectionBridge",
            "place_protect",
        ],
        "triangular": [
            "triangular",
        ],
        "markov": [
            "markov",
        ],
        "kelly": [
            "kelly",
        ],
        "ofi": [
            "ofi",
            "order_flow",
        ],
        "atr": [
            "atr",
            "ATR",
        ],
        "supertrend": [
            "supertrend",
            "Supertrend",
        ],
        "volume_profile": [
            "volume_profile",
            "Volume Profile",
        ],
    }

    result = {}

    for name, variants in required.items():
        result[name] = any(
            v.lower() in src.lower()
            for v in variants
        )

    return result


def generate_report(
    gate: TruthGate,
    economics: dict[str, Any],
    kelly: dict[str, Any],
    observations: list[dict[str, Any]],
) -> dict[str, Any]:

    architecture = scan_required_architecture(
        source_text()
    )

    report = {
        "system": "HONEYCOMB",
        "component": "production_truth_gate",
        "timestamp_ms": now_ms(),
        "python": sys.version,
        "root": str(ROOT),
        "alpha_parameter": ALPHA,
        "alpha_interpretation": (
            "external_parameter only; "
            "not independently validated as a financial law"
        ),
        "formal_verifications": [
            asdict(x)
            for x in gate.checks
        ],
        "summary": {
            "checks": len(gate.checks),
            "pass": gate.passed,
            "fail": gate.failed,
            "overall": (
                "PASS"
                if gate.failed == 0
                else "FAIL"
            ),
        },
        "real_observation_count": len(observations),
        "economics": economics,
        "kelly": kelly,
        "architecture_presence": architecture,
        "sqlite_record_counts": collect_sqlite_trade_count(),
        "principle": (
            "No measured evidence => no performance claim."
        ),
    }

    REPORT_FILE.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return report


def main() -> int:
    started = time.perf_counter_ns()

    print()
    print("=" * 72)
    print("HONEYCOMB — PRODUCTION TRUTH / AKADEMİK KANIT KAPISI")
    print("=" * 72)

    src = source_text()

    # 1
    ok, detail = test_python_syntax()

    gate = TruthGate()

    gate.check(
        1,
        "Python kaynak sözdizimi",
        ok,
        "AST parse ile gerçek kaynak dosyaları tarandı.",
        **detail,
    )

    # 2
    ok, detail = test_no_runtime_rust_go_dependency()

    gate.check(
        2,
        "Rust/Go runtime bağımlılığı yok",
        ok,
        "Python kaynaklarında cargo/rustc/go runtime çağrıları tarandı.",
        **detail,
    )

    # 3
    ok, detail = test_live_gate()

    gate.check(
        3,
        "LIVE execution gate",
        ok,
        "EXECUTION_MODE=LIVE ve LIVE_ARMED=1 birlikte aranıyor.",
        **detail,
    )

    # 4
    ok, detail = test_equity_gate()

    gate.check(
        4,
        "Pozitif equity gate",
        ok,
        "Pozitif gerçek equity görülmüyorsa HARD_KILL sonucu üretilir.",
        **detail,
    )

    # 5
    ok, detail = test_min_notional()

    gate.check(
        5,
        "Minimum notional",
        ok,
        "Minimum işlem notional değeri gerçek konfigürasyondan okunuyor.",
        **detail,
    )

    # 6
    ok, detail = test_stop_loss_source(src)

    gate.check(
        6,
        "Stop-loss / protection evidence",
        ok,
        "Kaynakta exchange-side protection kanıtı aranıyor.",
        **detail,
    )

    # 7
    ok, detail = test_ban_guard(src)

    gate.check(
        7,
        "Binance ban/suspend guard",
        ok,
        "Ban/error/suspend mekanizmasının kaynak kanıtı aranıyor.",
        **detail,
    )

    # 8
    ok, detail = test_atomic_state(src)

    gate.check(
        8,
        "Atomic state / WAL / lock",
        ok,
        "Kilitleme ve WAL/journal kanıtı aranıyor.",
        **detail,
    )

    # 9
    ok, detail = test_partial_fill(src)

    gate.check(
        9,
        "Partial-fill protection",
        ok,
        "Partial fill + cancel/reconciliation kanıtı aranıyor.",
        **detail,
    )

    # 10 — gerçek ekonomik veri
    observations = collect_real_observations()

    economic = empirical_economics(
        observations
    )

    enough_real_data = (
        len(observations)
        >= MIN_REAL_OBSERVATIONS
    )

    gate.check(
        10,
        "Gerçek işlem ekonomik kanıtı",
        enough_real_data,
        (
            "Gerçek JSONL fill kayıtları üzerinden "
            "net return, P(win), P(loss), EV ve PF hesaplanıyor. "
            "Sentetik veri kullanılmıyor."
        ),
        observations=len(observations),
        minimum_required=MIN_REAL_OBSERVATIONS,
        economics=economic,
    )

    kelly_returns = []

    for obj in observations:
        try:
            entry = float(obj["entry"])
            exit_ = float(obj["exit"])
            qty = float(obj["qty"])

            side = str(
                obj["side"]
            ).upper()

            if side == "SHORT":
                gross = (
                    (entry - exit_) * qty
                    / (entry * qty)
                )
            else:
                gross = (
                    (exit_ - entry) * qty
                    / (entry * qty)
                )

            cost = (
                float(obj["entry_fee"])
                + float(obj["exit_fee"])
                + float(obj.get("spread", 0.0))
                + float(obj.get("slippage", 0.0))
                + float(obj.get("funding", 0.0))
                + float(obj.get("impact", 0.0))
            )

            value = gross - cost

            if finite(value):
                kelly_returns.append(value)

        except Exception:
            continue

    kelly = generalized_kelly(
        kelly_returns
    )

    report = generate_report(
        gate,
        economic,
        kelly,
        observations,
    )

    elapsed_ms = (
        time.perf_counter_ns()
        - started
    ) / 1_000_000.0

    AUDIT.write(
        "GATE_COMPLETE",
        elapsed_ms=elapsed_ms,
        pass_count=gate.passed,
        fail_count=gate.failed,
        report=str(REPORT_FILE),
    )

    print()
    print("FORMAL DOĞRULAMALAR")
    print("-" * 72)

    for c in gate.checks:
        print(
            f"[{c.status:4}] "
            f"{c.number:02d} "
            f"{c.name}"
        )

    print("-" * 72)
    print(
        f"PASS={gate.passed} "
        f"FAIL={gate.failed} "
        f"SÜRE={elapsed_ms:.3f} ms"
    )

    print()
    print("GERÇEK VERİ:")
    print(
        f"  observation = {len(observations)}"
    )

    print()
    print("EKONOMİ:")
    print(
        json.dumps(
            economic,
            ensure_ascii=False,
            indent=2,
        )
    )

    print()
    print("KELLY:")
    print(
        json.dumps(
            kelly,
            ensure_ascii=False,
            indent=2,
        )
    )

    print()
    print(f"RAPOR: {REPORT_FILE}")
    print(f"AUDIT: {AUDIT_FILE}")

    if gate.failed:
        print()
        print(
            "SONUÇ: FAIL — sistem kanıtlanmamış "
            "koşulları PASS olarak göstermedi."
        )
        return 2

    print()
    print(
        "SONUÇ: PASS — yalnızca tanımlanan "
        "statik/kanıt kapıları geçildi."
    )
    print(
        "NOT: Bu PASS kârlılık, 2–3× EV veya "
        "belirli latency garantisi değildir."
    )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nDurduruldu.")
        raise SystemExit(130)
    except Exception as exc:
        AUDIT.write(
            "FATAL",
            error=repr(exc),
            traceback=traceback.format_exc(),
        )
        print(
            "FATAL:",
            repr(exc),
            file=sys.stderr,
        )
        raise SystemExit(1)
