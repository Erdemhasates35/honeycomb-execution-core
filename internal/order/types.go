package order

import "time"

type Side string

const (
	SideLong  Side = "LONG"
	SideShort Side = "SHORT"
)

type ExecutionRole string

const (
	RoleMaker ExecutionRole = "maker"
	RoleTaker ExecutionRole = "taker"
)

type OpenRequest struct {
	Symbol             string        `json:"symbol"`
	Side               Side          `json:"side"`
	Size               float64       `json:"size"`
	Leverage           float64       `json:"leverage"`
	Exchange           string        `json:"exchange"`
	ExpectedGrossPct   float64       `json:"expected_gross_pct"`
	EntryRole          ExecutionRole `json:"entry_role"`
	ExitRole           ExecutionRole `json:"exit_role"`
}

type CloseRequest struct {
	Symbol   string `json:"symbol"`
	Exchange string `json:"exchange"`
}

type Position struct {
	ID        string    `json:"id"`
	Symbol    string    `json:"symbol"`
	Side      Side      `json:"side"`
	Size      float64   `json:"size"`
	Leverage  float64   `json:"leverage"`
	Entry     float64   `json:"entry"`
	Exchange  string    `json:"exchange"`
	Mode      string    `json:"mode"`
	OpenedAt  time.Time `json:"opened_at"`
	Status    string    `json:"status"`
}

type OrderResult struct {
	Success  bool      `json:"success"`
	OrderID  string    `json:"order_id,omitempty"`
	Message  string    `json:"message"`
	Mode     string    `json:"mode"`
	Position *Position `json:"position,omitempty"`
}
