package order

import (
	"fmt"
	"sync"
	"time"

	"github.com/Erdemhasates35/honeycomb-execution-core/internal/config"
	"github.com/Erdemhasates35/honeycomb-execution-core/internal/edge"
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
	return &Router{cfg: cfg, risk: rm, positions: make(map[string]*Position), logs: make([]string, 0, 200)}
}

func (r *Router) log(msg string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	line := time.Now().UTC().Format(time.RFC3339Nano) + " " + msg
	r.logs = append(r.logs, line)
	if len(r.logs) > 200 {
		r.logs = r.logs[len(r.logs)-200:]
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
		copy := *p
		out = append(out, &copy)
	}
	return out
}

func (r *Router) Open(req OpenRequest) OrderResult {
	if err := req.Validate(); err != nil {
		r.log(fmt.Sprintf("REJECT open: validation=%s", err))
		return OrderResult{Success: false, Message: err.Error(), Mode: r.cfg.Mode}
	}
	if !r.risk.AllowNewOrder() {
		r.log("REJECT open: risk state not allowing new orders")
		return OrderResult{Success: false, Message: "risk_state_blocks_new_orders", Mode: r.cfg.Mode}
	}
	if req.Leverage > r.cfg.MaxLeverage {
		r.log("REJECT open: configured leverage limit exceeded")
		return OrderResult{Success: false, Message: "leverage_limit_exceeded", Mode: r.cfg.Mode}
	}

	edgeIn := edge.Input{GrossPercent: 0.20, FeePercent: 0.08, FundingPercent: 0.02, SlippagePercent: 0.04, SpreadPercent: 0.02, LatencyCostPct: 0.01, ExecRiskPercent: 0.02}
	res := edge.Calculate(edgeIn, r.cfg.MinEdgePercent)
	if !res.Allowed {
		r.log(fmt.Sprintf("REJECT open: edge=%.4f reason=%s", res.ExpectedNet, res.Reason))
		return OrderResult{Success: false, Message: res.Reason, Mode: r.cfg.Mode}
	}

	id := fmt.Sprintf("pos_%d", time.Now().UnixNano())
	pos := &Position{ID: id, Symbol: req.Symbol, Side: req.Side, Size: req.Size, Leverage: req.Leverage, Exchange: req.Exchange, Mode: r.cfg.Mode, OpenedAt: time.Now().UTC(), Status: "OPEN"}
	if r.cfg.Mode == "live" {
		if r.cfg.BinanceAPIKey == "" && r.cfg.BitgetAPIKey == "" {
			r.log("LIVE rejected: no exchange API keys configured")
			return OrderResult{Success: false, Message: "live_mode_requires_api_keys", Mode: "live"}
		}
		r.log(fmt.Sprintf("LIVE open requested %s %s size=%.6f", req.Side, req.Symbol, req.Size))
	} else {
		r.log(fmt.Sprintf("PAPER open %s %s size=%.6f lev=%.0fx", req.Side, req.Symbol, req.Size, req.Leverage))
	}

	r.mu.Lock()
	r.positions[id] = pos
	r.mu.Unlock()
	r.risk.RecordSuccess()
	return OrderResult{Success: true, OrderID: id, Message: "position_opened", Mode: r.cfg.Mode, Position: pos}
}

func (r *Router) Close(req CloseRequest) OrderResult {
	if req.Symbol == "" {
		return OrderResult{Success: false, Message: "symbol_required", Mode: r.cfg.Mode}
	}
	r.mu.Lock()
	var target *Position
	for _, p := range r.positions {
		if p.Symbol == req.Symbol && p.Status == "OPEN" {
			target = p
			break
		}
	}
	if target == nil {
		r.mu.Unlock()
		return OrderResult{Success: false, Message: "position_not_found", Mode: r.cfg.Mode}
	}
	target.Status = "CLOSED"
	result := *target
	r.mu.Unlock()
	r.log(fmt.Sprintf("%s close %s id=%s", r.cfg.Mode, req.Symbol, result.ID))
	return OrderResult{Success: true, OrderID: result.ID, Message: "position_closed", Mode: r.cfg.Mode, Position: &result}
}
