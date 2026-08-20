package exchange

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/Erdemhasates35/honeycomb-execution-core/internal/config"
)

type Binance struct { cfg *config.Config; client *http.Client }
type Position struct { Symbol string `json:"symbol"`; PositionAmt string `json:"positionAmt"` }
type orderResponse struct { OrderID int64 `json:"orderId"`; AvgPrice string `json:"avgPrice"` }

func NewBinance(cfg *config.Config) *Binance { return &Binance{cfg: cfg, client: &http.Client{Timeout: 8 * time.Second}} }

func (b *Binance) signed(method, path string, q url.Values, out any) error {
	q.Set("timestamp", strconv.FormatInt(time.Now().UnixMilli(), 10))
	q.Set("recvWindow", "5000")
	mac := hmac.New(sha256.New, []byte(b.cfg.BinanceSecret)); _, _ = mac.Write([]byte(q.Encode()))
	q.Set("signature", hex.EncodeToString(mac.Sum(nil)))
	req, err := http.NewRequest(method, b.cfg.BinanceBaseURL+path+"?"+q.Encode(), nil); if err != nil { return err }
	req.Header.Set("X-MBX-APIKEY", b.cfg.BinanceAPIKey); req.Header.Set("User-Agent", "honeycomb-live/1.0")
	res, err := b.client.Do(req); if err != nil { return err }; defer res.Body.Close(); body, _ := io.ReadAll(res.Body)
	if res.StatusCode < 200 || res.StatusCode >= 300 { return fmt.Errorf("binance http=%d body=%s", res.StatusCode, string(body)) }
	if out != nil && len(body) > 0 { return json.Unmarshal(body, out) }; return nil
}

func (b *Binance) price(symbol string) (float64, error) {
	req, err := http.NewRequest(http.MethodGet, b.cfg.BinanceBaseURL+"/fapi/v1/ticker/price?symbol="+url.QueryEscape(strings.ToUpper(symbol)), nil); if err != nil { return 0, err }
	res, err := b.client.Do(req); if err != nil { return 0, err }; defer res.Body.Close(); if res.StatusCode != http.StatusOK { body, _ := io.ReadAll(res.Body); return 0, fmt.Errorf("ticker http=%d body=%s", res.StatusCode, string(body)) }
	var x struct{ Price string `json:"price"` }; if err := json.NewDecoder(res.Body).Decode(&x); err != nil { return 0, err }; return strconv.ParseFloat(x.Price, 64)
}

func (b *Binance) setLeverage(symbol string, lev int) error { q := url.Values{}; q.Set("symbol", strings.ToUpper(symbol)); q.Set("leverage", strconv.Itoa(lev)); return b.signed(http.MethodPost, "/fapi/v1/leverage", q, &struct{}{}) }

func (b *Binance) Open(symbol, side string, quantity float64, leverage int, clientOrderID string) (string, float64, error) {
	if quantity <= 0 { return "", 0, fmt.Errorf("quantity must be positive") }; if leverage < 1 || float64(leverage) > b.cfg.MaxLeverage { return "", 0, fmt.Errorf("leverage exceeds configured maximum") }
	price, err := b.price(symbol); if err != nil { return "", 0, err }
	margin := quantity * price / float64(leverage); cap := b.cfg.MaxCapitalUSDT * b.cfg.TradeCapitalPercent / 100
	if margin > cap { return "", 0, fmt.Errorf("margin %.4f exceeds capital cap %.4f", margin, cap) }
	if b.cfg.MaxPositionSizeUSDT > 0 && quantity*price > b.cfg.MaxPositionSizeUSDT { return "", 0, fmt.Errorf("notional exceeds MAX_POSITION_SIZE_USDT") }
	if err := b.setLeverage(symbol, leverage); err != nil { return "", 0, err }
	q := url.Values{}; q.Set("symbol", strings.ToUpper(symbol)); q.Set("side", side); q.Set("type", "MARKET"); q.Set("quantity", strconv.FormatFloat(quantity, 'f', 8, 64)); q.Set("newClientOrderId", clientOrderID)
	var r orderResponse; if err := b.signed(http.MethodPost, "/fapi/v1/order", q, &r); err != nil { return "", 0, err }; avg, _ := strconv.ParseFloat(r.AvgPrice, 64); if avg == 0 { avg = price }; return strconv.FormatInt(r.OrderID, 10), avg, nil
}

func (b *Binance) Close(symbol string) (string, float64, error) {
	var positions []Position; if err := b.signed(http.MethodGet, "/fapi/v2/positionRisk", url.Values{"symbol": []string{strings.ToUpper(symbol)}}, &positions); err != nil { return "", 0, err }
	for _, p := range positions { amt, _ := strconv.ParseFloat(p.PositionAmt, 64); if amt == 0 { continue }; side, qty := "BUY", amt; if amt > 0 { side = "SELL" }
		q := url.Values{}; q.Set("symbol", strings.ToUpper(symbol)); q.Set("side", side); q.Set("type", "MARKET"); q.Set("quantity", strconv.FormatFloat(qty, 'f', 8, 64)); q.Set("reduceOnly", "true"); q.Set("newClientOrderId", "hc-close-"+strconv.FormatInt(time.Now().UnixNano(), 10))
		var r orderResponse; if err := b.signed(http.MethodPost, "/fapi/v1/order", q, &r); err != nil { return "", 0, err }; avg, _ := strconv.ParseFloat(r.AvgPrice, 64); return strconv.FormatInt(r.OrderID, 10), avg, nil
	}; return "", 0, fmt.Errorf("no open position for %s", symbol)
}
