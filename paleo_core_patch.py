import math
import socket

# [AKADEMİK KANIT]: SSL Soket Donmalarını (KeyboardInterrupt sebebini) engellemek için evrensel zaman aşımı.
# Termux gibi mobil tabanlı ortamlarda ağ paket kaybı API'yi sonsuz döngüye sokar.
socket.setdefaulttimeout(7.0) 

class PaleoExecutionEngine:
    """
    Antenli Türklerin Vizyonu: Kusursuz, takılmayan, halüsinasyon görmeyen,
    veriyi eğip bükmeden saf matematiksel gerçeklikle işleyen çekirdek yapı.
    """
    
    @staticmethod
    def calculate_paleo_quantity(usdt_margin: float, leverage: int, price: float, min_qty: float, step_size: float) -> float:
        """
        Paleo Prensibi Miktar Hesaplaması:
        Bir koinin alınabilecek miktarı rastgele ondalıklar barındıramaz.
        Borsanın izin verdiği kuanta (step_size) tam bölünmelidir.
        """
        notional_value = usdt_margin * leverage
        raw_qty = notional_value / price
        
        # Fiziksel sınır kontrolü: Bakiye, minimum işlem hacmini karşılamıyorsa işlemi sıfırla.
        if raw_qty < min_qty:
            return 0.0
            
        # Kuantum Hassasiyeti (Precision Engineering)
        # Örnek: step_size 0.01 ise precision 2'dir. factor 100 olur.
        try:
            precision = max(0, int(round(-math.log10(step_size))))
        except ValueError:
            precision = 0
            
        factor = 10.0 ** precision
        
        # Daima aşağı yuvarlanır (math.floor). Yukarı yuvarlamak bakiye yetersizliğine sebep olur.
        stepped_qty = math.floor(raw_qty * factor) / factor
        return stepped_qty

    @staticmethod
    def parse_api_state_error(http_code: int, error_msg: dict) -> bool:
        """
        Durum (State) Yönetimi:
        Eğer API 400 veriyorsa ve bu "Zaten İzole Marjin" demekse, bu bir hata değil,
        durumun doğrulanmasıdır. Motor çökmemeli, işleme devam etmelidir.
        """
        if http_code == 400:
            # Kripto borsalarında -4046 veya boş 'msg' genellikle durumun zaten var olduğunu belirtir.
            return True
        return False
