package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"

	"github.com/joho/godotenv"
)

type Config struct {
	Mode string
	HTTPPort string
	MaxDrawdownPercent float64
	MaxSlippageTolerance float64
	MinEdgePercent float64
	MaxLeverage float64
	MaxPositionSizeUSDT float64
	MaxCapitalUSDT float64
	TradeCapitalPercent float64
	CircuitBreakerThreshold int
	CircuitBreakerCooldown int
	BinanceAPIKey string
	BinanceSecret string
	BinanceBaseURL string
	BinanceWSSURL string
	BitgetAPIKey string
	BitgetSecret string
	BitgetPassphrase string
	BitgetBaseURL string
	OpenRouterAPIKey string
	GroqAPIKey string
	RedisURL string
}

func Load() (*Config, error) {
	_ = godotenv.Load()
	mode := strings.ToLower(strings.TrimSpace(getEnv("EXECUTION_MODE", "paper")))
	if mode != "paper" && mode != "live" { return nil, fmt.Errorf("EXECUTION_MODE must be paper or live") }
	cfg := &Config{
		Mode: mode, HTTPPort: getEnv("HTTP_PORT", "8080"),
		MaxDrawdownPercent: getEnvFloat("MAX_DRAWDOWN_PERCENT", 0.01), MaxSlippageTolerance: getEnvFloat("MAX_SLIPPAGE_TOLERANCE", 0.005), MinEdgePercent: getEnvFloat("MIN_EDGE_PERCENT", 0.05),
		MaxLeverage: getEnvFloat("MAX_LEVERAGE", 5), MaxPositionSizeUSDT: getEnvFloat("MAX_POSITION_SIZE_USDT", 500), MaxCapitalUSDT: getEnvFloat("MAX_CAPITAL_USDT", 0), TradeCapitalPercent: getEnvFloat("TRADE_CAPITAL_PCT", 10),
		CircuitBreakerThreshold: getEnvInt("CIRCUIT_BREAKER_THRESHOLD", 3), CircuitBreakerCooldown: getEnvInt("CIRCUIT_BREAKER_COOLDOWN_SEC", 10),
		BinanceAPIKey: os.Getenv("BINANCE_API_KEY"), BinanceSecret: os.Getenv("BINANCE_SECRET"), BinanceBaseURL: getEnv("BINANCE_BASE_URL", "https://fapi.binance.com"), BinanceWSSURL: getEnv("BINANCE_WSS_URL", "wss://fstream.binance.com/ws"),
		BitgetAPIKey: os.Getenv("BITGET_API_KEY"), BitgetSecret: os.Getenv("BITGET_SECRET"), BitgetPassphrase: os.Getenv("BITGET_PASSPHRASE"), BitgetBaseURL: getEnv("BITGET_BASE_URL", "https://api.bitget.com"),
		OpenRouterAPIKey: os.Getenv("OPENROUTER_API_KEY"), GroqAPIKey: os.Getenv("GROQ_API_KEY"), RedisURL: getEnv("REDIS_URL", "redis://127.0.0.1:6379"),
	}
	if cfg.MaxLeverage < 1 || cfg.MaxLeverage > 50 { return nil, fmt.Errorf("MAX_LEVERAGE must be between 1 and 50") }
	if cfg.TradeCapitalPercent <= 0 || cfg.TradeCapitalPercent > 10 { return nil, fmt.Errorf("TRADE_CAPITAL_PCT must be >0 and <=10") }
	if cfg.MaxCapitalUSDT <= 0 { return nil, fmt.Errorf("MAX_CAPITAL_USDT must be >0") }
	if mode == "live" && (cfg.BinanceAPIKey == "" || cfg.BinanceSecret == "") { return nil, fmt.Errorf("live mode requires BINANCE_API_KEY and BINANCE_SECRET") }
	if mode == "live" && strings.Contains(strings.ToLower(cfg.BinanceBaseURL), "testnet") { return nil, fmt.Errorf("live mode cannot use Binance testnet endpoint") }
	return cfg, nil
}
func getEnv(k, def string) string { if v := os.Getenv(k); v != "" { return v }; return def }
func getEnvFloat(k string, def float64) float64 { if v := os.Getenv(k); v != "" { if f, err := strconv.ParseFloat(v,64); err == nil { return f } }; return def }
func getEnvInt(k string, def int) int { if v := os.Getenv(k); v != "" { if i, err := strconv.Atoi(v); err == nil { return i } }; return def }
