package edge

import (
	"math"
	"testing"
)

func TestCalculateRejectsNonFiniteInput(t *testing.T) {
	result := Calculate(Input{GrossPercent: math.NaN()}, 0.05)
	if result.Allowed || result.Reason != "invalid_edge_input" {
		t.Fatalf("expected invalid input rejection, got %+v", result)
	}
}

func TestCalculateRejectsNegativeCosts(t *testing.T) {
	result := Calculate(Input{GrossPercent: 0.2, FeePercent: -0.1}, 0.05)
	if result.Allowed || result.Reason != "invalid_edge_input" {
		t.Fatalf("expected negative cost rejection, got %+v", result)
	}
}

func TestCalculateAllowsPositiveNetEdge(t *testing.T) {
	result := Calculate(Input{GrossPercent: 0.2, FeePercent: 0.02, FundingPercent: 0.01}, 0.05)
	if !result.Allowed || result.Reason != "edge_positive" {
		t.Fatalf("expected positive edge, got %+v", result)
	}
}
