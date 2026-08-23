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

func roleRateBPS(cfg *config.Config, role ExecutionRole) float64 {
	if role == RoleMaker {
		return cfg.MakerFeeBPS
	}
	return cfg.TakerFeeBPS
}

func (r *Router) executionCostPercent(req OpenRequest) float64 {
	entry := req.EntryRole
	exit := req.ExitRole
	if entry == "" {
		entry = RoleTaker
	}
	if exit == "" {
		exit = RoleTaker
	}
	feeBPS := roleRateBPS(r.cfg, entry) + roleRateBPS(r.cfg, exit)
	return feeBPS/100.0 +
		r.cfg.SlippageBPS/100.0 +
		r.cfg.SpreadBPS/100.0 +
		r.cfg.FundingBufferBPS/100.0 +
		r.cfg.OtherCostBPS/100.0
}

func (r *Router) Open(req OpenRequest) OrderResult {
	if !r.risk.AllowNewOrder() {
		r.log("REJECT open: risk state not allowing new orders")
		return OrderResult{Success: false, Message: "risk_state_blocks_new_orders", Mode: r.cfg.Mode}
	}

	if req.Size <= 0 || req.Size > r.cfg.MaxPositionSizeUSDT || req.Leverage <= 0 || req.Leverage > r.cfg.MaxLeverage {
		return OrderResult{Success: false, Message: "invalid_size_or_leverage", Mode: r.cfg.Mode}
	}
	if req.ExpectedGrossPct <= 0 {
		return OrderResult{Success: false, Message: "expected_gross_pct_required", Mode: r.cfg.Mode}
	}

	entryRole := req.EntryRole
	exitRole := req.ExitRole
	if entryRole == "" {
		entryRole = RoleTaker
	}
	if exitRole == "" {
		exitRole = RoleTaker
	}
	if (entryRole != RoleMaker && entryRole != RoleTaker) || (exitRole != RoleMaker && exitRole != RoleTaker) {
		return OrderResult{Success: false, Message: "invalid_execution_role", Mode: r.cfg.Mode}
	}

	costPct := r.executionCostPercent(req)
	edgeIn := edge.Input{
		GrossPercent:    req.ExpectedGrossPct,
		FeePercent:      (roleRateBPS(r.cfg, entryRole) + roleRateBPS(r.cfg, exitRole)) / 100.0,
		FundingPercent:  r.cfg.FundingBufferBPS / 100.0,
		SlippagePercent: r.cfg.SlippageBPS / 100.0,
		SpreadPercent:   r.cfg.SpreadBPS / 100.0,
		LatencyCostPct:   0,
		ExecRiskPercent: r.cfg.AdverseBufferPercent,
	}
	res := edge.Calculate(edgeIn, r.cfg.MinEdgePercent)
	if !res.Allowed {
		r.log(fmt.Sprintf("REJECT open: gross=%.4f cost=%.4f net=%.4f reason=%s", req.ExpectedGrossPct, costPct, res.ExpectedNet, res.Reason))
		return OrderResult{Success: false, Message: res.Reason, Mode: r.cfg.Mode}
	}

	// This Go router is not an exchange adapter. Never report a local stub as a live fill.
	if r.cfg.Mode == "live" {
		r.log("LIVE rejected: exchange execution adapter is not wired into internal/order.Router")
		return OrderResult{Success: false, Message: "live_exchange_adapter_not_wired", Mode: "live"}
	}

	id := fmt.Sprintf("pos_%d", time.Now().UnixNano())
	pos := &Position{ID: id, Symbol: req.Symbol, Side: req.Side, Size: req.Size, Leverage: req.Leverage, Entry: 0, Exchange: req.Exchange, Mode: r.cfg.Mode, OpenedAt: time.Now().UTC(), Status: "OPEN"}

	r.log(fmt.Sprintf("%s open %s %s size=%.6f lev=%.0fx gross=%.4f%% cost=%.4f%% net=%.4f%%", r.cfg.Mode, req.Side, req.Symbol, req.Size, req.Leverage, req.ExpectedGrossPct, costPct, res.ExpectedNet))
	r.mu.Lock()
	r.positions[id] = pos
	r.mu.Unlock()
	r.risk.RecordSuccess()

	return OrderResult{Success: true, OrderID: id, Message: "position_opened", Mode: r.cfg.Mode, Position: pos}
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
	return OrderResult{Success: true, OrderID: target.ID, Message: "position_closed", Mode: r.cfg.Mode, Position: target}
}
