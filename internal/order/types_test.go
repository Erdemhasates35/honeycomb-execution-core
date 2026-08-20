package order

import "testing"

func TestOpenRequestValidate(t *testing.T) {
	valid := OpenRequest{Symbol: "BTCUSDT", Side: SideLong, Size: 0.001, Leverage: 5, Exchange: "binance"}
	if err := valid.Validate(); err != nil {
		t.Fatalf("valid request rejected: %v", err)
	}
	cases := []OpenRequest{
		{Symbol: "", Side: SideLong, Size: 1, Leverage: 1, Exchange: "binance"},
		{Symbol: "BTCUSDT", Side: Side("BAD"), Size: 1, Leverage: 1, Exchange: "binance"},
		{Symbol: "BTCUSDT", Side: SideLong, Size: 0, Leverage: 1, Exchange: "binance"},
		{Symbol: "BTCUSDT", Side: SideLong, Size: 1, Leverage: 0, Exchange: "binance"},
		{Symbol: "BTCUSDT", Side: SideLong, Size: 1, Leverage: 1, Exchange: "unknown"},
	}
	for i, request := range cases {
		if err := request.Validate(); err == nil {
			t.Fatalf("case %d unexpectedly passed validation", i)
		}
	}
}
