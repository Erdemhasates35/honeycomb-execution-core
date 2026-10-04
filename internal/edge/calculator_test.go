package edge

import "testing"

const edgeTolerance = 1e-12

func almostEqual(a, b float64) bool {
	return a-b <= edgeTolerance && b-a <= edgeTolerance
}

func TestCalculateNetEdge(t *testing.T) {
	got := Calculate(Input{
		GrossPercent: 0.30, FeePercent: 0.08, FundingPercent: 0.02,
		SlippagePercent: 0.04, SpreadPercent: 0.02, LatencyCostPct: 0.01,
		ExecRiskPercent: 0.02,
	}, 0.05)
	if !got.Allowed { t.Fatalf("expected positive edge, got %+v", got) }
	if !almostEqual(got.ExpectedNet, 0.11) { t.Fatalf("expected 0.11 net edge, got %.12f", got.ExpectedNet) }
}

func TestCalculateRejectsBelowMinimum(t *testing.T) {
	got := Calculate(Input{GrossPercent: 0.20, FeePercent: 0.08, FundingPercent: 0.02, SlippagePercent: 0.04, SpreadPercent: 0.02, LatencyCostPct: 0.01, ExecRiskPercent: 0.02}, 0.05)
	if got.Allowed { t.Fatal("edge below threshold must be rejected") }
	if !almostEqual(got.ExpectedNet, 0.01) { t.Fatalf("expected 0.01 net edge, got %.12f", got.ExpectedNet) }
}
