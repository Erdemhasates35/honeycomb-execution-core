package config

import (
	"os"
	"strconv"

	"github.com/joho/godotenv"
)

type Config struct {
	Mode string // paper | live

	HTTPPort string

	MaxDrawdownPercent      float64
	MaxSlippageTolerance    float64
	MinEdgePercent          float64
	MaxLeverage             float64
	MaxPositionSizeUSDT     float64
	RiskPerTradePercent     float64
	MaxDailyLossPercent     float64
	AdverseBufferPercent    float64
	CircuitBreakerThreshold int
	CircuitBreakerCooldown  int

	// Explicit execution economics. Units are bps: 1 bps = 0.01%.
	MakerFeeBPS       float64
	TakerFeeBPS       float64
	SlippageBPS       float64
	SpreadBPS         float64
	FundingBufferBPS  float64
	OtherCostBPS      float64

	BinanceAPIKey  string
	BinanceSecret  string
	BinanceBaseURL string
	BinanceWSSURL  string

	BitgetAPIKey     string
	BitgetSecret     string
	BitgetPassphrase string
	BitgetBaseURL    string

	OpenRouterAPIKey string
	GroqAPIKey       string

	RedisURL string
}

func Load() (*Config, error) {
	_ = godotenv.Load()

	cfg := &Config{
		Mode:                    getEnv("EXECUTION_MODE", "paper"),
		HTTPPort:                getEnv("HTTP_PORT", "8080"),
		MaxDrawdownPercent:      getEnvFloat("MAX_DRAWDOWN_PERCENT", 0.01),
		MaxSlippageTolerance:    getEnvFloat("MAX_SLIPPAGE_TOLERANCE", 0.005),
		MinEdgePercent:          getEnvFloat("MIN_EDGE_PERCENT", 0.15),
		MaxLeverage:             getEnvFloat("MAX_LEVERAGE", 20),
		MaxPositionSizeUSDT:     getEnvFloat("MAX_POSITION_SIZE_USDT", 200),
		RiskPerTradePercent:     getEnvFloat("RISK_PER_TRADE_PCT", 0.75),
		MaxDailyLossPercent:     getEnvFloat("MAX_DAILY_LOSS_PCT", 3.0),
		AdverseBufferPercent:    getEnvFloat("ADVERSE_BUFFER_PCT", 0.10),
		CircuitBreakerThreshold: getEnvInt("CIRCUIT_BREAKER_THRESHOLD", 3),
		CircuitBreakerCooldown:  getEnvInt("CIRCUIT_BREAKER_COOLDOWN_SEC", 10),

		MakerFeeBPS:      getEnvFloat("MAKER_FEE_BPS", 2),
		TakerFeeBPS:      getEnvFloat("TAKER_FEE_BPS", 5),
		SlippageBPS:      getEnvFloat("SLIPPAGE_BPS", 1),
		SpreadBPS:        getEnvFloat("SPREAD_BPS", 0.5),
		FundingBufferBPS: getEnvFloat("FUNDING_BUFFER_BPS", 1),
		OtherCostBPS:     getEnvFloat("OTHER_COST_BPS", 0),

		BinanceAPIKey:  os.Getenv("BINANCE_API_KEY"),
		BinanceSecret:  os.Getenv("BINANCE_SECRET"),
		BinanceBaseURL: getEnv("BINANCE_BASE_URL", "https://fapi.binance.com"),
		BinanceWSSURL:  getEnv("BINANCE_WSS_URL", "wss://fstream.binance.com/ws"),

		BitgetAPIKey:     os.Getenv("BITGET_API_KEY"),
		BitgetSecret:     os.Getenv("BITGET_SECRET"),
		BitgetPassphrase: os.Getenv("BITGET_PASSPHRASE"),
		BitgetBaseURL:    getEnv("BITGET_BASE_URL", "https://api.bitget.com"),

		OpenRouterAPIKey: os.Getenv("OPENROUTER_API_KEY"),
		GroqAPIKey:       os.Getenv("GROQ_API_KEY"),

		RedisURL: getEnv("REDIS_URL", "redis://127.0.0.1:6379"),
	}

	if cfg.Mode != "paper" && cfg.Mode != "live" {
		cfg.Mode = "paper"
	}
	return cfg, nil
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
