package edge

// ExpectedNet = Gross - Fee - Funding - Slippage - Spread - LatencyCost - ExecRisk

type Input struct {
	GrossPercent     float64
	FeePercent       float64
	FundingPercent   float64
	SlippagePercent  float64
	SpreadPercent    float64
	LatencyCostPct   float64
	ExecRiskPercent  float64
}

type Result struct {
	ExpectedNet float64
	Allowed     bool
	Reason      string
}

func Calculate(in Input, minEdge float64) Result {
	net := in.GrossPercent -
		in.FeePercent -
		in.FundingPercent -
		in.SlippagePercent -
		in.SpreadPercent -
		in.LatencyCostPct -
		in.ExecRiskPercent

	if net > minEdge {
		return Result{ExpectedNet: net, Allowed: true, Reason: "edge_positive"}
	}
	return Result{ExpectedNet: net, Allowed: false, Reason: "edge_below_minimum"}
}
