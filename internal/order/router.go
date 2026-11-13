package order

import (
	"fmt"
	"sync"
	"time"

	"github.com/Erdemhasates35/honeycomb-execution-core/internal/config"
		"github.com/Erdemhasates35/honeycomb-execution-core/internal/risk"
)

type Router struct {
	cfg       *config.Config
	risk      *risk.Manager
	mu        sync.RWMutex
	positions map[string]*Position
	logs      []string
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

	if req.Symbol == "" || req.Size <= 0 || req.Leverage <= 0 || req.Leverage > r.cfg.MaxLeverage ||
		(req.Side != SideLong && req.Side != SideShort) {
		return OrderResult{Success: false, Message: "invalid_order_request", Mode: r.cfg.Mode}
	}

	// Fail closed: this Go router currently has no live venue adapter and no
	// connected, timestamped order-book/edge provider. Never manufacture an
	// edge estimate or report an order as successful without a venue receipt.
	if r.cfg.Mode == "live" {
		r.log("LIVE rejected: venue execution adapter and live edge provider are unavailable")
		return OrderResult{Success: false, Message: "live_execution_adapter_unavailable", Mode: "live"}
	}

	r.log("PAPER rejected: explicit paper execution adapter is not connected to this Go router")
	return OrderResult{Success: false, Message: "paper_execution_adapter_unavailable", Mode: r.cfg.Mode}
}

func (r *Router) Close(req CloseRequest) OrderResult {
	if r.cfg.Mode == "live" {
		r.log("LIVE close rejected: venue execution adapter is unavailable")
		return OrderResult{Success: false, Message: "live_execution_adapter_unavailable", Mode: "live"}
	}
	r.log("PAPER close rejected: explicit paper execution adapter is not connected to this Go router")
	return OrderResult{Success: false, Message: "paper_execution_adapter_unavailable", Mode: r.cfg.Mode}
}
