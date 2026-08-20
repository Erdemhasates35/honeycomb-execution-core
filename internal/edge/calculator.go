package edge

import "math"

// ExpectedNet = Gross - Fee - Funding - Slippage - Spread - LatencyCost - ExecRisk.
type Input struct {
	GrossPercent    float64
	FeePercent      float64
	FundingPercent  float64
	SlippagePercent float64
	SpreadPercent   float64
	LatencyCostPct  float64
	ExecRiskPercent float64
}

type Result struct {
	ExpectedNet float64
	Allowed     bool
	Reason      string
}

func (in Input) Validate() error {
	values := [...]float64{in.GrossPercent, in.FeePercent, in.FundingPercent, in.SlippagePercent, in.SpreadPercent, in.LatencyCostPct, in.ExecRiskPercent}
	for _, value := range values {
		if math.IsNaN(value) || math.IsInf(value, 0) {
			return ErrNonFiniteInput
		}
		if value < 0 {
			return ErrNegativeCost
		}
	}
	return nil
}

func Calculate(in Input, minEdge float64) Result {
	if err := in.Validate(); err != nil || math.IsNaN(minEdge) || math.IsInf(minEdge, 0) || minEdge < 0 {
		return Result{Allowed: false, Reason: "invalid_edge_input"}
	}
	net := in.GrossPercent - in.FeePercent - in.FundingPercent - in.SlippagePercent - in.SpreadPercent - in.LatencyCostPct - in.ExecRiskPercent
	if net > minEdge {
		return Result{ExpectedNet: net, Allowed: true, Reason: "edge_positive"}
	}
	return Result{ExpectedNet: net, Allowed: false, Reason: "edge_below_minimum"}
}
