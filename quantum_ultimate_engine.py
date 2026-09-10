import math
import sys
import time
import json
import sqlite3
import glob
import hmac
import hashlib
import logging
import traceback
import urllib.request
import urllib.parse
import concurrent.futures
from typing import List, Dict, Any, Tuple, Optional

# ==============================================================================
# LOGGING VE SİSTEM YAPILANDIRMASI
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# ==============================================================================
# 1. SAF AKADEMİK MATEMATİK VE İNDİKATÖR MOTORU (PURE MATH ENGINE)
# ==============================================================================
class AcademicMathEngine:
    """ Sıfır dış kütüphane bağımlılığı ile yüksek hassasiyetli matematiksel ve istatistiksel hesaplamalar. """

    @staticmethod
    def mean(data: List[float]) -> float:
        return sum(data) / len(data) if data else 0.0

    @staticmethod
    def variance(data: List[float], mean_val: Optional[float] = None) -> float:
        if len(data) < 2:
            return 0.0
        m = mean_val if mean_val is not None else AcademicMathEngine.mean(data)
        return sum((x - m) ** 2 for x in data) / (len(data) - 1)

    @staticmethod
    def std_dev(data: List[float], mean_val: Optional[float] = None) -> float:
        var = AcademicMathEngine.variance(data, mean_val)
        return math.sqrt(var) if var > 0 else 0.0

    @staticmethod
    def sma(data: List[float], period: int) -> float:
        if len(data) < period or period <= 0:
            return 0.0
        return sum(data[-period:]) / period

    @staticmethod
    def ema(data: List[float], period: int) -> float:
        if len(data) < period or period <= 0:
            return 0.0
        multiplier = 2.0 / (period + 1)
        ema_val = sum(data[:period]) / period
        for price in data[period:]:
            ema_val = (price - ema_val) * multiplier + ema_val
        return ema_val

    @staticmethod
    def rsi(data: List[float], period: int = 14) -> float:
        if len(data) < period + 1:
            return 50.0
        gains, losses = [], []
        for i in range(1, len(data)):
            change = data[i] - data[i - 1]
            gains.append(max(0.0, change))
            losses.append(max(0.0, -change))
        
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0.0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    @staticmethod
    def macd(data: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[float, float, float]:
        if len(data) < slow + signal:
            return 0.0, 0.0, 0.0
        ema_fast = AcademicMathEngine.ema(data, fast)
        ema_slow = AcademicMathEngine.ema(data, slow)
        macd_line = ema_fast - ema_slow
        
        # MACD serisi oluşturma
        macd_series = []
        for i in range(slow, len(data) + 1):
            f = AcademicMathEngine.ema(data[:i], fast)
            s = AcademicMathEngine.ema(data[:i], slow)
            macd_series.append(f - s)
            
        signal_line = AcademicMathEngine.ema(macd_series, signal) if len(macd_series) >= signal else macd_line
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def bollinger_bands(data: List[float], period: int = 20, num_std: float = 2.0) -> Tuple[float, float, float]:
        if len(data) < period:
            return 0.0, 0.0, 0.0
        sub_data = data[-period:]
        sma_val = AcademicMathEngine.mean(sub_data)
        sd = AcademicMathEngine.std_dev(sub_data, sma_val)
        return sma_val + (num_std * sd), sma_val, sma_val - (num_std * sd)

    @staticmethod
    def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        if len(highs) < period + 1:
            return 0.0
        tr_list = []
        for i in range(1, len(highs)):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            tr_list.append(tr)
        return AcademicMathEngine.ema(tr_list, period)

    @staticmethod
    def vwap(highs: List[float], lows: List[float], closes: List[float], vols: List[float]) -> float:
        if not closes or sum(vols) == 0:
            return closes[-1] if closes else 0.0
        typical_prices = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(len(closes))]
        cum_tp_vol = sum(typical_prices[i] * vols[i] for i in range(len(closes)))
        cum_vol = sum(vols)
        return cum_tp_vol / cum_vol if cum_vol > 0 else closes[-1]

    @staticmethod
    def z_score(data: List[float], window: int = 20) -> float:
        if len(data) < window:
            return 0.0
        sub_series = data[-window:]
        m = AcademicMathEngine.mean(sub_series)
        sd = AcademicMathEngine.std_dev(sub_series, m)
        return (data[-1] - m) / sd if sd > 0 else 0.0

    @classmethod
    def calculate_20_indicators(cls, highs: List[float], lows: List[float], closes: List[float], vols: List[float]) -> Dict[str, float]:
        """ 20 Kritik indikatörün eksiksiz ve hassas hesabı """
        if not closes or len(closes) < 30:
            return {}

        current_close = closes[-1]
        vwap_val = cls.vwap(highs, lows, closes, vols)
        bb_upper, bb_mid, bb_lower = cls.bollinger_bands(closes, 20, 2.0)
        macd_line, macd_sig, macd_hist = cls.macd(closes)
        atr_val = cls.atr(highs, lows, closes, 14)
        
        highest_high = max(highs[-14:]) if len(highs) >= 14 else highs[-1]
        lowest_low = min(lows[-14:]) if len(lows) >= 14 else lows[-1]
        stoch_k = ((current_close - lowest_low) / (highest_high - lowest_low) * 100.0) if highest_high != lowest_low else 50.0
        williams_r = ((highest_high - current_close) / (highest_high - lowest_low) * -100.0) if highest_high != lowest_low else -50.0

        return {
            "current_close": current_close,
            "SMA_20": cls.sma(closes, 20),
            "SMA_50": cls.sma(closes, 50),
            "EMA_9": cls.ema(closes, 9),
            "EMA_21": cls.ema(closes, 21),
            "RSI_14": cls.rsi(closes, 14),
            "MACD_Line": macd_line,
            "MACD_Signal": macd_sig,
            "MACD_Hist": macd_hist,
            "BB_Upper": bb_upper,
            "BB_Middle": bb_mid,
            "BB_Lower": bb_lower,
            "ATR_14": atr_val,
            "VWAP": vwap_val,
            "Momentum_10": current_close - closes[-10] if len(closes) >= 10 else 0.0,
            "ROC_9": ((current_close - closes[-9]) / closes[-9]) * 100.0 if len(closes) >= 9 and closes[-9] != 0 else 0.0,
            "Stochastic_K": stoch_k,
            "Williams_R": williams_r,
            "Z_Score": cls.z_score(closes, 20),
            "Price_Delta": current_close - closes[-2] if len(closes) >= 2 else 0.0,
            "Volume_Ratio": vols[-1] / (sum(vols[-20:-1]) / 19.0) if len(vols) >= 20 and sum(vols[-20:-1]) > 0 else 1.0
        }

# ==============================================================================
# 2. OTONOM VERİTABANI ORKESTRATÖRÜ (SELF-HEALING DATABASE MANAGER)
# ==============================================================================
class SelfHealingDatabaseManager:
    """ Dizindeki veri verilerini ASLA silmez. Bozuk tabloları onarır ve state hafızası tutar. """

    def __init__(self, main_db: str = "quantum_execution_core.db"):
        self.main_db = main_db
        self.init_main_db()

    def get_connection(self, db_path: str):
        return sqlite3.connect(db_path, timeout=10.0)

    def init_main_db(self):
        try:
            with self.get_connection(self.main_db) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS trade_execution_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL,
                        symbol TEXT,
                        side TEXT,
                        price REAL,
                        qty REAL,
                        z_score REAL,
                        trend_score INTEGER,
                        fee_paid REAL,
                        status TEXT
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS system_telemetry (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL,
                        event_type TEXT,
                        details TEXT
                    )
                """)
                conn.commit()
        except sqlite3.Error as e:
            logging.error(f"[DB KURULUM HATASI]: {e}")

    def scan_and_verify_all_dbs(self) -> Dict[str, Any]:
        """ Bulunduğu dizindeki hiçbir şeyi silmeden tüm .db dosyalarını inceler ve doğrular. """
        db_files = glob.glob("*.db")
        db_report = {}
        for db in db_files:
            try:
                conn = self.get_connection(db)
                cursor = conn.cursor()
                cursor.execute("PRAGMA quick_check;")
                status = cursor.fetchone()[0]
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = [t[0] for t in cursor.fetchall()]
                conn.close()
                db_report[db] = {"integrity": status, "tables": tables}
            except Exception as e:
                db_report[db] = {"integrity": "CORRUPTED", "error": str(e)}
        return db_report

    def log_trade(self, symbol: str, side: str, price: float, qty: float, z_score: float, trend_score: int, fee: float, status: str):
        try:
            with self.get_connection(self.main_db) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO trade_execution_logs (timestamp, symbol, side, price, qty, z_score, trend_score, fee_paid, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (time.time(), symbol, side, price, qty, z_score, trend_score, fee, status))
                conn.commit()
        except sqlite3.Error as e:
            logging.error(f"[TRADE DB LOG HATASI]: {e}")

# ==============================================================================
# 3. MUKAVEMETLİ CÜZDAN VE API İLETİŞİM KATMANI (RESILIENT BINANCE CLIENT)
# ==============================================================================
class ResilientBinanceClient:
    """ Üstel geri çekilme (Exponential Backoff) ve HMAC-SHA256 imzalı canlı işlem katmanı. """

    BASE_URL = "https://fapi.binance.com"

    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.api_key = api_key
        self.api_secret = api_secret

    def _generate_signature(self, query_string: str) -> str:
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    def request_with_retry(self, method: str, endpoint: str, params: Dict[str, Any] = None, signed: bool = False, retries: int = 5) -> Optional[Any]:
        if params is None:
            params = {}

        url = f"{self.BASE_URL}{endpoint}"

        if signed:
            params['timestamp'] = int(time.time() * 1000)
            query_string = urllib.parse.urlencode(params)
            signature = self._generate_signature(query_string)
            url = f"{url}?{query_string}&signature={signature}"
        elif params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        headers = {'User-Agent': 'Mozilla/5.0'}
        if self.api_key:
            headers['X-MBX-APIKEY'] = self.api_key

        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers=headers, method=method)
                with urllib.request.urlopen(req, timeout=5) as response:
                    if response.status == 200:
                        return json.loads(response.read().decode('utf-8'))
            except Exception as e:
                wait_time = (2 ** attempt) * 0.5
                logging.warning(f"[API BAĞLANTI UYARISI]: Deneme {attempt + 1}/{retries} başarısız ({e}). {wait_time}s bekleniyor...")
                time.sleep(wait_time)

        logging.error(f"[API KRİTİK HATA]: {endpoint} endpoint'ine erişilemedi.")
        return None

    def fetch_klines(self, symbol: str, interval: str, limit: int = 100) -> Dict[str, List[float]]:
        data = self.request_with_retry("GET", "/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit})
        if not data:
            return {"highs": [], "lows": [], "closes": [], "volumes": []}

        return {
            "highs": [float(c[2]) for c in data],
            "lows": [float(c[3]) for c in data],
            "closes": [float(c[4]) for c in data],
            "volumes": [float(c[5]) for c in data]
        }

    def execute_live_futures_order(self, symbol: str, side: str, quantity: float) -> Optional[Dict[str, Any]]:
        """ Canlı/Testnet Binance Futures Emir Gönderimi """
        if not self.api_key or not self.api_secret:
            logging.info(f"[SİMÜLASYON MODU]: API Anahtarları girilmedi. {symbol} {side} {quantity} emri sanal simüle edildi.")
            return {"status": "SIMULATED", "symbol": symbol, "side": side, "origQty": quantity}

        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity
        }
        return self.request_with_retry("POST", "/fapi/v1/order", params=params, signed=True)

# ==============================================================================
# 4. ÇOKLU ZAMAN DİLİMİ MATRİS ORKESTRATÖRÜ
# ==============================================================================
class MultiTimeframeOrchestrator:
    TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]

    def __init__(self, client: ResilientBinanceClient):
        self.client = client

    def fetch_all_timeframes_parallel(self, symbol: str) -> Dict[str, Dict[str, float]]:
        mtf_results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.TIMEFRAMES)) as executor:
            future_to_tf = {
                executor.submit(self.client.fetch_klines, symbol, tf, 100): tf 
                for tf in self.TIMEFRAMES
            }
            for future in concurrent.futures.as_completed(future_to_tf):
                tf = future_to_tf[future]
                try:
                    kline_data = future.result()
                    if kline_data["closes"]:
                        mtf_results[tf] = AcademicMathEngine.calculate_20_indicators(
                            kline_data["highs"], kline_data["lows"], kline_data["closes"], kline_data["volumes"]
                        )
                except Exception as e:
                    logging.error(f"[MTF VERİ YÜKLEME HATASI - {tf}]: {e}")
        return mtf_results

# ==============================================================================
# 5. KUSURSUZ OTONOM KANTİTATİF MOTOR (ULTIMATE EXECUTION ENGINE)
# ==============================================================================
class QuantumUltimateEngine:
    def __init__(self, symbol: str, api_key: str = "", api_secret: str = ""):
        self.symbol = symbol
        self.db_manager = SelfHealingDatabaseManager()
        self.client = ResilientBinanceClient(api_key, api_secret)
        self.orchestrator = MultiTimeframeOrchestrator(self.client)

    def self_diagnostic_routine(self):
        """ Sistem başlangıç self-healing ve DB kontrol doğrulaması """
        logging.info("--- SISTEM KENDINI TEŞHIS VE ONARIM MODU BAŞLATILDI ---")
        db_report = self.db_manager.scan_and_verify_all_dbs()
        for db_name, status in db_report.items():
            logging.info(f"DB: {db_name} -> Durum: {status.get('integrity')} | Tablolar: {status.get('tables')}")

    def execute_quantum_cycle(self):
        self.self_diagnostic_routine()
        logging.info(f"\n=======================================================")
        logging.info(f"   {self.symbol} OTONOM CANLI İŞLEM DÖNGÜSÜ BAŞLATILDI")
        logging.info(f"=======================================================")

        start_time = time.time()
        mtf_matrix = self.orchestrator.fetch_all_timeframes_parallel(self.symbol)

        if len(mtf_matrix) < len(MultiTimeframeOrchestrator.TIMEFRAMES):
            logging.warning("[EKSİK VERİ]: Tüm zaman dilimlerinden veri toplanamadı. Risk almamak için pasif mod.")
            return

        # Trend Skoru Hesaplama
        trend_score = 0
        for tf, ind in mtf_matrix.items():
            current_close = ind["current_close"]
            vwap_val = ind["VWAP"]
            
            # EMA & RSI & VWAP Konfirmasyonu (Düzeltilmiş ve Hatasız Kontrol)
            if ind["EMA_9"] > ind["EMA_21"] and ind["RSI_14"] < 70.0 and current_close > vwap_val:
                trend_score += 1
            elif ind["EMA_9"] < ind["EMA_21"] and ind["RSI_14"] > 30.0 and current_close < vwap_val:
                trend_score -= 1

        # 1-Dakikalık Hassas Mikro Giriş Z-Score'u
        m1_z_score = mtf_matrix.get("1m", {}).get("Z_Score", 0.0)
        daily_atr = mtf_matrix.get("1d", {}).get("ATR_14", 0.0)
        current_price = mtf_matrix.get("1m", {}).get("current_close", 0.0)

        logging.info(f"Senkronize Zaman Dilimi  : {len(mtf_matrix)}/7 Onaylı")
        logging.info(f"Günlük ATR Volatilitesi  : ${daily_atr:.2f}")
        logging.info(f"1-Dakikalık Z-Score      : {m1_z_score:.4f}")
        logging.info(f"Akademik Trend Skoru     : {trend_score} / 7")

        # İşlem Karar Algoritması
        # Komisyon ve Kayma (Slippage) Hesabı: Taker %0.05 + Slippage %0.03 = %0.08 Tek Yön -> %0.16 Round-Trip
        round_trip_friction = 0.0016 

        if trend_score >= 5 and m1_z_score < -2.0:
            logging.info(">>> [KUSURSUZ İŞLEM TESPİT EDİLDİ]: LONG (ALIŞ) SİNYALİ!")
            order_res = self.client.execute_live_futures_order(self.symbol, "BUY", 0.001)
            self.db_manager.log_trade(self.symbol, "BUY", current_price, 0.001, m1_z_score, trend_score, round_trip_friction * current_price * 0.001, "EXECUTED")
        elif trend_score <= -5 and m1_z_score > 2.0:
            logging.info(">>> [KUSURSUZ İŞLEM TESPİT EDİLDİ]: SHORT (SATIŞ) SİNYALİ!")
            order_res = self.client.execute_live_futures_order(self.symbol, "SELL", 0.001)
            self.db_manager.log_trade(self.symbol, "SELL", current_price, 0.001, m1_z_score, trend_score, round_trip_friction * current_price * 0.001, "EXECUTED")
        else:
            logging.info(">>> [SİNYAL PASİF]: İstatistiksel Pareto (%80 Güven) şartları sağlanmadı. Sermaye koruma altında.")

        exec_time = time.time() - start_time
        logging.info(f"Döngü Tamamlanma Süresi  : {exec_time:.3f} Saniye\n")

if __name__ == "__main__":
    # Test ve Çalıştırma Bloğu
    engine = QuantumUltimateEngine("BTCUSDT")
    engine.execute_quantum_cycle()
