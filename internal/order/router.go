package order

import (
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/Erdemhasates35/honeycomb-execution-core/internal/config"
	"github.com/Erdemhasates35/honeycomb-execution-core/internal/edge"
	"github.com/Erdemhasates35/honeycomb-execution-core/internal/exchange"
	"github.com/Erdemhasates35/honeycomb-execution-core/internal/risk"
)

type Router struct { cfg *config.Config; risk *risk.Manager; binance *exchange.Binance; mu sync.RWMutex; positions map[string]*Position; logs []string }
func NewRouter(cfg *config.Config, rm *risk.Manager) *Router { return &Router{cfg:cfg,risk:rm,binance:exchange.NewBinance(cfg),positions:make(map[string]*Position),logs:make([]string,0,200)} }
func (r *Router) log(msg string) { r.mu.Lock(); defer r.mu.Unlock(); line:=time.Now().UTC().Format(time.RFC3339Nano)+" "+msg; r.logs=append([]string{line},r.logs...);if len(r.logs)>200{r.logs=r.logs[:200]} }
func (r *Router) Logs() []string { r.mu.RLock();defer r.mu.RUnlock();out:=make([]string,len(r.logs));copy(out,r.logs);return out }
func (r *Router) Positions() []*Position { r.mu.RLock();defer r.mu.RUnlock();out:=make([]*Position,0,len(r.positions));for _,p:=range r.positions{out=append(out,p)};return out }

func (r *Router) Open(req OpenRequest) OrderResult {
	if !r.risk.AllowNewOrder(){r.log("REJECT open: risk state");return OrderResult{Message:"risk_state_blocks_new_orders",Mode:r.cfg.Mode}}
	if req.Symbol=="" || req.Size<=0 || req.Leverage<1 || req.Leverage>r.cfg.MaxLeverage{return OrderResult{Message:"invalid_symbol_size_or_leverage",Mode:r.cfg.Mode}}
	if req.Side!=SideLong && req.Side!=SideShort{return OrderResult{Message:"side_must_be_LONG_or_SHORT",Mode:r.cfg.Mode}}
	if req.Exchange==""{req.Exchange="binance"}; req.Exchange=strings.ToLower(req.Exchange)
	if r.cfg.Mode=="live" {
		if req.Exchange!="binance" { return OrderResult{Message:"live_exchange_not_implemented",Mode:"live"} }
		if req.ExpectedNetPercent < r.cfg.MinEdgePercent { return OrderResult{Message:"live_edge_below_minimum",Mode:"live"} }
		side:="BUY";if req.Side==SideShort{side="SELL"};cid:=fmt.Sprintf("hc-%d",time.Now().UnixNano())
		orderID,entry,err:=r.binance.Open(req.Symbol,side,req.Size,int(req.Leverage),cid);if err!=nil{r.log("LIVE open rejected: "+err.Error());r.risk.RecordFailure();return OrderResult{Message:err.Error(),Mode:"live"}}
		pos:=&Position{ID:orderID,Symbol:req.Symbol,Side:req.Side,Size:req.Size,Leverage:req.Leverage,Entry:entry,Exchange:req.Exchange,Mode:"live",OpenedAt:time.Now().UTC(),Status:"OPEN"}
		r.mu.Lock();r.positions[orderID]=pos;r.mu.Unlock();r.risk.RecordSuccess();r.log(fmt.Sprintf("LIVE OPEN %s %s qty=%.8f lev=%.0fx order=%s",req.Side,req.Symbol,req.Size,req.Leverage,orderID));return OrderResult{Success:true,OrderID:orderID,Message:"live_order_submitted",Mode:"live",Position:pos}
	}
	edgeIn:=edge.Input{GrossPercent:req.ExpectedNetPercent+r.cfg.MinEdgePercent,FeePercent:0.08,FundingPercent:0.02,SlippagePercent:0.04,SpreadPercent:0.02,LatencyCostPct:0.01,ExecRiskPercent:0.02};res:=edge.Calculate(edgeIn,r.cfg.MinEdgePercent);if !res.Allowed{return OrderResult{Message:res.Reason,Mode:"paper"}}
	id:=fmt.Sprintf("paper_%d",time.Now().UnixNano());pos:=&Position{ID:id,Symbol:req.Symbol,Side:req.Side,Size:req.Size,Leverage:req.Leverage,Exchange:req.Exchange,Mode:"paper",OpenedAt:time.Now().UTC(),Status:"OPEN"};r.mu.Lock();r.positions[id]=pos;r.mu.Unlock();r.log(fmt.Sprintf("PAPER OPEN %s %s qty=%.8f",req.Side,req.Symbol,req.Size));r.risk.RecordSuccess();return OrderResult{Success:true,OrderID:id,Message:"paper_position_opened",Mode:"paper",Position:pos}
}

func (r *Router) Close(req CloseRequest) OrderResult {
	if req.Exchange==""{req.Exchange="binance"};if r.cfg.Mode=="live"{if strings.ToLower(req.Exchange)!="binance"{return OrderResult{Message:"live_exchange_not_implemented",Mode:"live"}};id,exit,err:=r.binance.Close(req.Symbol);if err!=nil{r.log("LIVE close rejected: "+err.Error());return OrderResult{Message:err.Error(),Mode:"live"}};r.mu.Lock();for _,p:=range r.positions{if p.Symbol==req.Symbol&&p.Status=="OPEN"{p.Status="CLOSED";if exit>0{p.Entry=p.Entry};break}};r.mu.Unlock();r.log(fmt.Sprintf("LIVE CLOSE %s order=%s",req.Symbol,id));return OrderResult{Success:true,OrderID:id,Message:"live_order_closed",Mode:"live"}}
	r.mu.Lock();defer r.mu.Unlock();for _,p:=range r.positions{if p.Symbol==req.Symbol&&p.Status=="OPEN"{p.Status="CLOSED";return OrderResult{Success:true,OrderID:p.ID,Message:"paper_position_closed",Mode:"paper",Position:p}}};return OrderResult{Message:"position_not_found",Mode:r.cfg.Mode}
}
