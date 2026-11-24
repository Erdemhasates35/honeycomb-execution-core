export function mean(values: number[]): number {
  if (values.length === 0 || values.some(value => !Number.isFinite(value))) throw new Error("mean requires finite observations");
  return values.reduce((sum,value) => sum + value,0) / values.length;
}

export function variance(values: number[]): number {
  if (values.length < 2) throw new Error("variance requires at least two observations");
  const average = mean(values);
  return values.reduce((sum,value) => sum + (value-average) ** 2,0) / (values.length-1);
}

export function standardDeviation(values: number[]): number {
  return Math.sqrt(variance(values));
}

export function pearsonCorrelation(left: number[], right: number[]): number {
  if (left.length !== right.length || left.length < 3) throw new Error("correlation requires equal arrays with at least three observations");
  const leftMean = mean(left);
  const rightMean = mean(right);
  const numerator = left.reduce((sum,value,index) => sum + (value-leftMean)*(right[index]-rightMean),0);
  const leftDenominator = Math.sqrt(left.reduce((sum,value) => sum + (value-leftMean) ** 2,0));
  const rightDenominator = Math.sqrt(right.reduce((sum,value) => sum + (value-rightMean) ** 2,0));
  if (leftDenominator === 0 || rightDenominator === 0) throw new Error("correlation is undefined for constant observations");
  return numerator / (leftDenominator*rightDenominator);
}

export function regressionSlope(values: number[]): number {
  if (values.length < 2 || values.some(value => !Number.isFinite(value))) throw new Error("regression requires at least two finite observations");
  const xMean = (values.length-1)/2;
  const yMean = mean(values);
  let numerator = 0;
  let denominator = 0;
  for (let index=0;index<values.length;index++) {
    numerator += (index-xMean)*(values[index]-yMean);
    denominator += (index-xMean) ** 2;
  }
  if (denominator === 0) throw new Error("regression slope is undefined");
  return numerator/denominator;
}

export function exponentialMovingAverage(values: number[], period: number): number {
  if (!Number.isInteger(period) || period < 1 || values.length < period || values.some(value => !Number.isFinite(value))) throw new Error("EMA input is invalid");
  const alpha = 2/(period+1);
  let result = mean(values.slice(0,period));
  for (const value of values.slice(period)) result = alpha*value+(1-alpha)*result;
  return result;
}

export function clamp(value: number, minimum: number, maximum: number): number {
  if (![value,minimum,maximum].every(Number.isFinite) || minimum>maximum) throw new Error("clamp bounds are invalid");
  return Math.min(maximum,Math.max(minimum,value));
}

export function assertPositive(value: number, name: string): void {
  if (!Number.isFinite(value) || value <= 0) throw new Error(name+" must be finite and positive");
}
