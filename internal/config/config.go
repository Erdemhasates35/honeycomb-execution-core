package config

import (
	"os"
	"strconv"
	"strings"
)

type Config struct {
	Mode string // paper | live
	HTTPPort string
	MaxDrawdownPercent float64
	MaxSlippageTolerance float64
	MinEdgePercent float64
	MaxLeverage float64
	MaxPositionSizeUSDT float64
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
	_ = loadDotEnv(".env")
	cfg := &Config{
		Mode: getEnv("EXECUTION_MODE", "paper"),
		HTTPPort: getEnv("HTTP_PORT", "8080"),
		MaxDrawdownPercent: getEnvFloat("MAX_DRAWDOWN_PERCENT", 0.01),
		MaxSlippageTolerance: getEnvFloat("MAX_SLIPPAGE_TOLERANCE", 0.005),
		MinEdgePercent: getEnvFloat("MIN_EDGE_PERCENT", 0.05),
		MaxLeverage: getEnvFloat("MAX_LEVERAGE", 5),
		MaxPositionSizeUSDT: getEnvFloat("MAX_POSITION_SIZE_USDT", 500),
		CircuitBreakerThreshold: getEnvInt("CIRCUIT_BREAKER_THRESHOLD", 3),
		CircuitBreakerCooldown: getEnvInt("CIRCUIT_BREAKER_COOLDOWN_SEC", 10),
		BinanceAPIKey: os.Getenv("BINANCE_API_KEY"),
		BinanceSecret: os.Getenv("BINANCE_SECRET"),
		BinanceBaseURL: getEnv("BINANCE_BASE_URL", "https://fapi.binance.com"),
		BinanceWSSURL: getEnv("BINANCE_WSS_URL", "wss://fstream.binance.com/ws"),
		BitgetAPIKey: os.Getenv("BITGET_API_KEY"),
		BitgetSecret: os.Getenv("BITGET_SECRET"),
		BitgetPassphrase: os.Getenv("BITGET_PASSPHRASE"),
		BitgetBaseURL: getEnv("BITGET_BASE_URL", "https://api.bitget.com"),
		OpenRouterAPIKey: os.Getenv("OPENROUTER_API_KEY"),
		GroqAPIKey: os.Getenv("GROQ_API_KEY"),
		RedisURL: getEnv("REDIS_URL", "redis://127.0.0.1:6379"),
	}
	if cfg.Mode != "paper" && cfg.Mode != "live" {
		cfg.Mode = "paper"
	}
	return cfg, nil
}

func loadDotEnv(path string) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	for _, raw := range strings.Split(string(data), "\n") {
		line := strings.TrimSpace(raw)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		parts := strings.SplitN(line, "=", 2)
		if len(parts) != 2 {
			continue
		}
		key := strings.TrimSpace(parts[0])
		value := strings.TrimSpace(parts[1])
		if key == "" {
			continue
		}
		value = strings.Trim(value, "'\"")
		if _, exists := os.LookupEnv(key); !exists {
			_ = os.Setenv(key, value)
		}
	}
	return nil
}

func getEnv(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func getEnvFloat(k string, def float64) float64 {
	if v := os.Getenv(k); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}
	return def
}

func getEnvInt(k string, def int) int {
	if v := os.Getenv(k); v != "" {
		if i, err := strconv.Atoi(v); err == nil {
			return i
		}
	}
	return def
}
