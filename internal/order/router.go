package order

import (
	"fmt"
	"sync"
	"time"

	"github.com/Erdemhasates35/honeycomb-execution-core/internal/config"
	"github.com/Erdemhasates35/honeycomb-execution-core/internal/edge"
	"github.com/Erdemhasates35/honeycomb-execution-core/internal/risk"
	"github.com/google/uuid"
)

// Not: google/uuid yerine basit id üretimi kullanıyoruz (bağımlılık azaltmak için).

type Router struct {
	cfg      *config.Config
	risk     *risk.Manager
	mu       sync.RWMutex
	positions map[string]*Position
	logs     []string
}

func NewRouter(cfg *config.Config, rm *risk.Manager) *Router {
	return &Router{
		cfg:       cfg,
		risk:      rm,
		positions: make(map[string]*Position),
		logs:      make([]string, 0, 200),
	}
}

func (r *Router) log(msg string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	line := time.Now().Format("15:04:05") + " " + msg
	r.logs = append([]string{line}, r.logs...)
	if len(r.logs) > 200 {
		r.logs = r.logs[:200]
	}
}

func (r *Router) Logs() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]string, len(r.logs))
	copy(out, r.logs)
	return out
}

func (r *Router) Positions() []*Position {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]*Position, 0, len(r.positions))
	for _, p := range r.positions {
		out = append(out, p)
	}
	return out
}

func (r *Router) Open(req OpenRequest) OrderResult {
	if !r.risk.AllowNewOrder() {
		r.log("REJECT open: risk state not allowing new orders")
		return OrderResult{Success: false, Message: "risk_state_blocks_new_orders", Mode: r.cfg.Mode}
	}

	if req.Size <= 0 || req.Leverage <= 0 || req.Leverage > r.cfg.MaxLeverage {
		return OrderResult{Success: false, Message: "invalid_size_or_leverage", Mode: r.cfg.Mode}
	}

	// Basit edge kontrolü (canlı veri bağlanınca gerçek orderbook'tan gelecek)
	edgeIn := edge.Input{
		GrossPercent:    0.20, // örnek — gerçekte orderbook'tan hesaplanır
		FeePercent:      0.08,
		FundingPercent:  0.02,
		SlippagePercent: 0.04,
		SpreadPercent:   0.02,
		LatencyCostPct:  0.01,
		ExecRiskPercent: 0.02,
	}
	res := edge.Calculate(edgeIn, r.cfg.MinEdgePercent)
	if !res.Allowed {
		r.log(fmt.Sprintf("REJECT open: edge=%.4f reason=%s", res.ExpectedNet, res.Reason))
		return OrderResult{Success: false, Message: res.Reason, Mode: r.cfg.Mode}
	}

	id := fmt.Sprintf("pos_%d", time.Now().UnixNano())
	pos := &Position{
		ID:       id,
		Symbol:   req.Symbol,
		Side:     req.Side,
		Size:     req.Size,
		Leverage: req.Leverage,
		Entry:    0, // live'da mark price ile dolar
		Exchange: req.Exchange,
		Mode:     r.cfg.Mode,
		OpenedAt: time.Now().UTC(),
		Status:   "OPEN",
	}

	if r.cfg.Mode == "live" {
		// LIVE: gerçek exchange API çağrısı burada yapılır.
		// Key yoksa veya imza hatalıysa fail döner.
		if r.cfg.BinanceAPIKey == "" && r.cfg.BitgetAPIKey == "" {
			r.log("LIVE rejected: no exchange API keys configured")
			return OrderResult{Success: false, Message: "live_mode_requires_api_keys", Mode: "live"}
		}
		// TODO: gerçek signed REST order — key'ler doluysa burada Binance/Bitget client çağrılır.
		// Şu an iskelet: key var kabul edilip paper benzeri kayıt (güvenlik için gerçek emir
		// gönderimi kullanıcı key'lerini doğruladıktan sonra aktif edilir).
		r.log(fmt.Sprintf("LIVE open requested %s %s size=%.6f (keys present — wire real client next)", req.Side, req.Symbol, req.Size))
	} else {
		r.log(fmt.Sprintf("PAPER open %s %s size=%.6f lev=%.0fx", req.Side, req.Symbol, req.Size, req.Leverage))
	}

	r.mu.Lock()
	r.positions[id] = pos
	r.mu.Unlock()
	r.risk.RecordSuccess()

	return OrderResult{
		Success:  true,
		OrderID:  id,
		Message:  "position_opened",
		Mode:     r.cfg.Mode,
		Position: pos,
	}
}

func (r *Router) Close(req CloseRequest) OrderResult {
	r.mu.Lock()
	defer r.mu.Unlock()

	var target *Position
	for _, p := range r.positions {
		if p.Symbol == req.Symbol && p.Status == "OPEN" {
			target = p
			break
		}
	}
	if target == nil {
		return OrderResult{Success: false, Message: "position_not_found", Mode: r.cfg.Mode}
	}

	target.Status = "CLOSED"
	r.log(fmt.Sprintf("%s close %s id=%s", r.cfg.Mode, req.Symbol, target.ID))

	return OrderResult{
		Success:  true,
		OrderID:  target.ID,
		Message:  "position_closed",
		Mode:     r.cfg.Mode,
		Position: target,
	}
}

// uuid fallback without external dep
var _ = uuid.New
