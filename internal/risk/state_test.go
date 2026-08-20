package risk

import "testing"

func TestManagerOpensCircuitAtThreshold(t *testing.T) {
	m := NewManager(2, 60)
	m.RecordFail()
	if m.Current() == RED {
		t.Fatal("circuit opened before threshold")
	}
	m.RecordFail()
	if m.Current() != RED || m.AllowNewOrder() {
		t.Fatal("expected RED circuit state to block new orders")
	}
}

func TestManagerRejectsInvalidState(t *testing.T) {
	m := NewManager(1, 1)
	if err := m.SetState(State("INVALID")); err != ErrInvalidState {
		t.Fatalf("expected ErrInvalidState, got %v", err)
	}
}
