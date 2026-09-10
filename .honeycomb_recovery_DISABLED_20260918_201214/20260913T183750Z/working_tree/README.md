# α-HONEYCOMB EXECUTION CORE (Go)

Gerçek emir motoru — Binance + Bitget Futures.

## Önemli (Dürüstlük)

- **Paper mode** varsayılandır. Gerçek para göndermez.
- **Live mode** sadece geçerli API key + secret ile ve `EXECUTION_MODE=live` iken çalışır.
- Linux x64 VPS içindir. Termux / Android desteklenmez.
- Control Plane (Vercel dashboard) bu servise HTTP ile bağlanır.

## Hızlı Kurulum (Ubuntu VPS)

```bash
# 1. Go kur
sudo apt update && sudo apt install -y golang-go redis-server git

# 2. Repo
git clone https://github.com/Erdemhasates35/honeycomb-execution-core.git
cd honeycomb-execution-core

# 3. Env
cp .env.example .env
nano .env   # key'leri doldur

# 4. Bağımlılık + çalıştır
go mod tidy
go run ./cmd/engine
```

Servis `http://VPS_IP:8080` üzerinde ayağa kalkar.

## API Endpoints

| Method | Path | Açıklama |
|--------|------|----------|
| GET | /health | Sağlık |
| GET | /status | Risk state, mode, equity özeti |
| POST | /order/open | Pozisyon aç (body: symbol, side, size, leverage) |
| POST | /order/close | Pozisyon kapat |
| GET | /positions | Açık pozisyonlar |
| GET | /logs | Son loglar |

## Edge Kuralı

```
ExpectedNet = Gross - Fee - Funding - Slippage - Spread - LatencyCost - ExecRisk
IF ExpectedNet > MinEdge AND RiskState in {GREEN, YELLOW} → ALLOW
ELSE → REJECT
```
