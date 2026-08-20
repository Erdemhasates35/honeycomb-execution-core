package main

import (
	"encoding/json"
	"log"
	"net/http"
	"time"

	"github.com/Erdemhasates35/honeycomb-execution-core/internal/config"
	"github.com/Erdemhasates35/honeycomb-execution-core/internal/order"
	"github.com/Erdemhasates35/honeycomb-execution-core/internal/risk"
)

func main() {
	cfg, err := config.Load(); if err != nil { log.Fatal(err) }
	rm := risk.NewManager(cfg.CircuitBreakerThreshold, cfg.CircuitBreakerCooldown); router := order.NewRouter(cfg, rm); mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) { writeJSON(w, map[string]any{"status":"ok","mode":cfg.Mode,"time":time.Now().UTC()}) })
	mux.HandleFunc("/status", func(w http.ResponseWriter, r *http.Request) { writeJSON(w,map[string]any{"mode":cfg.Mode,"risk_state":rm.Current(),"positions":len(router.Positions()),"min_edge":cfg.MinEdgePercent,"max_lev":cfg.MaxLeverage,"max_capital_usdt":cfg.MaxCapitalUSDT,"trade_capital_pct":cfg.TradeCapitalPercent}) })
	mux.HandleFunc("/positions", func(w http.ResponseWriter, r *http.Request) { writeJSON(w,router.Positions()) })
	mux.HandleFunc("/logs", func(w http.ResponseWriter, r *http.Request) { writeJSON(w,router.Logs()) })
	mux.HandleFunc("/order/open", func(w http.ResponseWriter, r *http.Request) { if r.Method!=http.MethodPost{http.Error(w,"method not allowed",405);return};var req order.OpenRequest;if err:=json.NewDecoder(r.Body).Decode(&req);err!=nil{http.Error(w,err.Error(),400);return};res:=router.Open(req);if !res.Success{writeJSONStatus(w,res,http.StatusBadRequest);return};writeJSONStatus(w,res,http.StatusOK) })
	mux.HandleFunc("/order/close", func(w http.ResponseWriter, r *http.Request) { if r.Method!=http.MethodPost{http.Error(w,"method not allowed",405);return};var req order.CloseRequest;if err:=json.NewDecoder(r.Body).Decode(&req);err!=nil{http.Error(w,err.Error(),400);return};res:=router.Close(req);if !res.Success{writeJSONStatus(w,res,http.StatusBadRequest);return};writeJSONStatus(w,res,http.StatusOK) })
	addr := ":"+cfg.HTTPPort; log.Printf("α-HONEYCOMB Execution Core starting mode=%s port=%s",cfg.Mode,cfg.HTTPPort); if cfg.Mode=="live"{log.Println("LIVE execution enabled: signed exchange orders only")}; if err:=http.ListenAndServe(addr,mux);err!=nil{log.Fatal(err)}
}
func writeJSON(w http.ResponseWriter,v any){writeJSONStatus(w,v,http.StatusOK)}
func writeJSONStatus(w http.ResponseWriter,v any,status int){w.Header().Set("Content-Type","application/json");w.WriteHeader(status);_ = json.NewEncoder(w).Encode(v)}
