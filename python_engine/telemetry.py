# python_engine/telemetry.py
from prometheus_client import Counter, Histogram, Gauge, start_http_server

orders_total = Counter('hc_orders_total', 'Total orders sent')
orders_errors = Counter('hc_orders_errors_total', 'Total order errors')
order_latency = Histogram('hc_order_latency_seconds', 'Order roundtrip latency seconds')
account_balance = Gauge('hc_account_balance_usdt', 'Account balance in USDT')

def start_metrics_server(port: int = 8000):
    start_http_server(port)
