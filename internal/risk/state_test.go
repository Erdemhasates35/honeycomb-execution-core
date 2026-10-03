package risk

import "testing"

func TestCircuitBreakerTransitionsToRed(t *testing.T) {
	m := NewManager(2, 60)
	m.RecordFail()
	if m.Current() != GREEN { t.Fatalf("expected GREEN after first failure, got %s", m.Current()) }
	m.RecordFail()
	if m.Current() != RED { t.Fatalf("expected RED after threshold, got %s", m.Current()) }
	if m.AllowNewOrder() { t.Fatal("RED must block new orders") }
}
