import ccxt
import json
import time

e = ccxt.binance({'enableRateLimit': True})
markets = e.fetch_markets()
symbols = []

for m in markets:
    sym = m.get('symbol')
    if not sym:
        continue
    
    info = {'symbol': sym, 'filters': []}
    prec = m.get('precision', {})
    
    if prec.get('amount') is not None:
        step = 10 ** (-prec['amount']) if prec['amount'] >= 0 else 0
    else:
        step = Decimal('0')
        
    info['filters'].append({
        'filterType': 'LOT_SIZE',
        'stepSize': str(step),
        'minQty': str(m.get('limits', {}).get('amount', {}).get('min', 0))
    })
    
    symbols.append(info)

with open('exchange_info.json', 'w') as f:
    json.dump({'symbols': symbols}, f, indent=2)

print(f"exchange_info.json yazıldı, toplam sembol sayısı: {len(symbols)}")
