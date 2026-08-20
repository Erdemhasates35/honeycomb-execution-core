package order

import (
	"errors"
	"strings"
	"time"
)

type Side string

const (
	SideLong  Side = "LONG"
	SideShort Side = "SHORT"
)

var (
	ErrInvalidSymbol   = errors.New("symbol must be non-empty")
	ErrInvalidSide     = errors.New("side must be LONG or SHORT")
	ErrInvalidSize     = errors.New("size must be positive and finite")
	ErrInvalidLeverage = errors.New("leverage must be positive and finite")
	ErrInvalidExchange = errors.New("exchange must be binance or bitget")
)

type OpenRequest struct {
	Symbol   string  `json:"symbol"`
	Side     Side    `json:"side"`
	Size     float64 `json:"size"`
	Leverage float64 `json:"leverage"`
	Exchange string  `json:"exchange"`
}

func (r OpenRequest) Validate() error {
	if strings.TrimSpace(r.Symbol) == "" {
		return ErrInvalidSymbol
	}
	if r.Side != SideLong && r.Side != SideShort {
		return ErrInvalidSide
	}
	if r.Size <= 0 || r.Size != r.Size || r.Size > 1e12 {
		return ErrInvalidSize
	}
	if r.Leverage <= 0 || r.Leverage != r.Leverage || r.Leverage > 1000 {
		return ErrInvalidLeverage
	}
	exchange := strings.ToLower(strings.TrimSpace(r.Exchange))
	if exchange != "binance" && exchange != "bitget" {
		return ErrInvalidExchange
	}
	return nil
}

type CloseRequest struct {
	Symbol   string `json:"symbol"`
	Exchange string `json:"exchange"`
}

type Position struct {
	ID       string    `json:"id"`
	Symbol   string    `json:"symbol"`
	Side     Side      `json:"side"`
	Size     float64   `json:"size"`
	Leverage float64   `json:"leverage"`
	Entry    float64   `json:"entry"`
	Exchange string    `json:"exchange"`
	Mode     string    `json:"mode"`
	OpenedAt time.Time `json:"opened_at"`
	Status   string    `json:"status"`
}

type OrderResult struct {
	Success  bool      `json:"success"`
	OrderID  string    `json:"order_id,omitempty"`
	Message  string    `json:"message"`
	Mode     string    `json:"mode"`
	Position *Position `json:"position,omitempty"`
}
