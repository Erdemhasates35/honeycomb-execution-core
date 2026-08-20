# α-HONEYCOMB EXECUTION CORE

Gerçek emir motoru — Binance USDT-M Futures.

## Canlı yürütme sözleşmesi

- `EXECUTION_MODE=live` yalnızca production Binance Futures endpoint'i ile kabul edilir.
- Canlı modda sahte/paper/mock fill oluşturulmaz. Gerçek Binance signed REST emri başarısızsa işlem başarısızdır.
- `MAX_CAPITAL_USDT` sermaye tavanıdır; `TRADE_CAPITAL_PCT` **%10'u aşamaz**.
- `MAX_LEVERAGE` **1–50** aralığında zorunludur.
- `MAX_POSITION_SIZE_USDT` ayrıca daha düşük bir notional tavanı uygulayabilir.
- Canlı açılış isteği gerçek edge verisi (`expected_net_percent`) taşımalı ve `MIN_EDGE_PERCENT` eşiğini geçmelidir.
- Testnet URL'si live modda fail-closed edilir.
- İdempotency için Binance `newClientOrderId` kullanılır.

## Çalıştırma

Linux x64 execution worker üzerinde `.env` doldurulduktan sonra:

```bash
go mod tidy
go test ./...
go run ./cmd/engine
```

Termux/Android tarafı execution worker değildir; kontrol/izleme istemcisi olarak kullanılmalıdır. Web/Android UI da yalnızca execution API'ye yetkili çağrı yapar; exchange secret'ları istemciye verilmez.

## API

| Method | Path | Açıklama |
|---|---|---|
| GET | /health | Servis sağlık + mode |
| GET | /status | Risk, pozisyon ve sermaye limitleri |
| POST | /order/open | Gerçek Binance MARKET emir açılışı (`live`) |
| POST | /order/close | Gerçek Binance pozisyon kapatılışı (`live`) |
| GET | /positions | Yerel execution durumu |
| GET | /logs | Execution logları |

`POST /order/open` body örneği: `{"symbol":"BTCUSDT","side":"LONG","size":0.001,"leverage":10,"exchange":"binance","expected_net_percent":0.20}`

## Mimari sınır

Lovable/Supabase/Vercel/Web/Android katmanı UI, auth, telemetry ve read-model içindir. Exchange secret ve gerçek emir yetkisi yalnızca Linux x64 execution worker'dadır. L3 risk kapısı router'ın önündedir; canlı adapter L3'ü atlayamaz.
