package edge

import "errors"

var (
	ErrNonFiniteInput = errors.New("edge input contains NaN or infinity")
	ErrNegativeCost   = errors.New("edge input contains a negative cost")
)
