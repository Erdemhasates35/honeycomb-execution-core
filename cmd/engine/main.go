package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/Erdemhasates35/honeycomb-execution-core/internal/config"
	"github.com/Erdemhasates35/honeycomb-execution-core/internal/order"
	"github.com/Erdemhasates35/honeycomb-execution-core/internal/risk"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		log.Fatal(err)
	}

	rm := risk.NewManager(cfg.CircuitBreakerThreshold, cfg.CircuitBreakerCooldown)
	router := order.NewRouter(cfg, rm)

	mux := http.NewServeMux()

	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, map[string]any{
			"status": "ok",
			"mode":   cfg.Mode,
			"time":   time.Now().UTC(),
		})
	})

	mux.HandleFunc("/status", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, map[string]any{
			"mode":       cfg.Mode,
			"risk_state": rm.Current(),
			"positions":  len(router.Positions()),
			"min_edge":   cfg.MinEdgePercent,
			"max_lev":    cfg.MaxLeverage,
		})
	})

	mux.HandleFunc("/positions", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, router.Positions())
	})

	mux.HandleFunc("/logs", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, router.Logs())
	})

	mux.HandleFunc("/order/open", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var req order.OpenRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		if req.Exchange == "" {
			req.Exchange = "binance"
		}
		res := router.Open(req)
		writeJSON(w, res)
	})

	mux.HandleFunc("/order/close", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var req order.CloseRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		res := router.Close(req)
		writeJSON(w, res)
	})

	addr := ":" + cfg.HTTPPort
	log.Printf("α-HONEYCOMB Execution Core starting mode=%s port=%s", cfg.Mode, cfg.HTTPPort)
	if cfg.Mode == "live" {
		log.Println("WARNING: LIVE mode — real keys required. Orders will not send without valid credentials.")
	}
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatal(err)
		o s.Exit(1)
	}
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(v)
}
