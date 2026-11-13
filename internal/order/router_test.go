package order

import (
	"testing"

	"github.com/Erdemhasates35/honeycomb-execution-core/internal/config"
	"github.com/Erdemhasates35/honeycomb-execution-core/internal/risk"
)

func newTestRouter(mode string) *Router {
	return NewRouter(&config.Config{Mode: mode, MaxLeverage: 5}, risk.NewManager(3, 1))
}

func validOpenRequest() OpenRequest {
	return OpenRequest{Symbol: "BTCUSDT", Side: SideLong, Size: 0.01, Leverage: 2, Exchange: "binance"}
}

func TestLiveOpenFailsClosedWithoutVenueAdapter(t *testing.T) {
	router := newTestRouter("live")
	result := router.Open(validOpenRequest())
	if result.Success {
		t.Fatal("live order must not report success without a venue adapter receipt")
	}
	if result.Message != "live_execution_adapter_unavailable" {
		t.Fatalf("unexpected rejection reason: %s", result.Message)
	}
	if got := len(router.Positions()); got != 0 {
		t.Fatalf("rejected order must not create a local position; got %d", got)
	}
}

func TestPaperOpenFailsClosedWithoutExplicitPaperAdapter(t *testing.T) {
	router := newTestRouter("paper")
	result := router.Open(validOpenRequest())
	if result.Success {
		t.Fatal("paper order must not report success without an explicit paper adapter")
	}
	if result.Message != "paper_execution_adapter_unavailable" {
		t.Fatalf("unexpected rejection reason: %s", result.Message)
	}
	if got := len(router.Positions()); got != 0 {
		t.Fatalf("rejected order must not create a local position; got %d", got)
	}
}

func TestLiveCloseFailsClosedWithoutVenueAdapter(t *testing.T) {
	result := newTestRouter("live").Close(CloseRequest{Symbol: "BTCUSDT", Exchange: "binance"})
	if result.Success || result.Message != "live_execution_adapter_unavailable" {
		t.Fatalf("live close must fail closed without venue adapter; got %+v", result)
	}
}

func TestInvalidOrderRequestRejected(t *testing.T) {
	req := validOpenRequest()
	req.Side = "BUY"
	result := newTestRouter("live").Open(req)
	if result.Success || result.Message != "invalid_order_request" {
		t.Fatalf("invalid side must be rejected; got %+v", result)
	}
}
