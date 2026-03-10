# V10 Findings: Statistical Validation — S4/S5 with 20 Runs

**Date**: 2026-03-08
**Baseline**: 100247c (V10)

## Purpose

Previous comparisons used 10 runs with high inter-run variance (S4 fixed_isolation
swung from 69ms to 102ms across V8/V10). Increased S4 and S5 to 20 runs for
reliable confidence intervals.

## S4 Multi-Node Results (20 runs, 32 nodes, 4 faults, 2-5x slowdown)

### P99 Latency (ms)
| Baseline | Mean | 95% CI | Range |
|----------|------|--------|-------|
| **adaptive** | **88.1** | **±20.4** | 37.0 - 135.8 |
| **fixed_isolation** | **83.9** | **±20.0** | 37.2 - 158.6 |
| fixed_shedding | 98.2 | ±15.8 | 54.0 - 157.0 |
| fixed_speculation | 116.8 | ±12.0 | 57.1 - 163.7 |
| no_mitigation | 120.5 | ±9.7 | 79.7 - 151.0 |

### P999 Latency (ms)
| Baseline | Mean | 95% CI | Range |
|----------|------|--------|-------|
| adaptive | 124.4 | ±26.9 | 47.9 - 193.5 |
| fixed_isolation | 126.5 | ±25.5 | 47.0 - 206.9 |
| fixed_shedding | 149.8 | ±18.2 | 93.7 - 208.8 |
| fixed_speculation | 171.0 | ±11.8 | 99.8 - 220.8 |
| no_mitigation | 171.7 | ±9.9 | 121.4 - 200.2 |

### S4 Analysis

**Critical discovery: V8's "adaptive is much worse than fixed_isolation" was noise.**

With 20 runs: adaptive (88.1±20.4) ≈ fixed_isolation (83.9±20.0). CIs overlap
completely. The V8 comparison of 69ms vs 109ms was comparing two single-seed
outliers in opposite directions.

Strategy ranking with statistical confidence:
1. **fixed_isolation ≈ adaptive** (indistinguishable, both ~85ms)
2. **fixed_shedding** (98ms, marginally worse)
3. **fixed_speculation ≈ no_mitigation** (117-120ms, clearly worse)

The enormous CI ranges (±20ms) come from S4's random slowdown generation
(uniform 2-5x). Each seed produces different fault severities, causing wide
variation. This is inherent to the scenario design, not fixable by more runs.

## S5 Fluctuating Results (20 runs, 32 nodes, 3 faults, 5x 8s/8s)

### P99 Latency (ms)
| Baseline | Mean | 95% CI | Range |
|----------|------|--------|-------|
| fixed_isolation | 115.6 | ±9.0 | 33.9 - 121.6 |
| adaptive | 119.6 | ±0.5 | 117.1 - 122.3 |
| fixed_shedding | 119.8 | ±0.5 | 117.5 - 121.3 |
| fixed_speculation | 120.4 | ±0.6 | 118.2 - 122.7 |
| no_mitigation | 121.4 | ±0.5 | 120.0 - 124.5 |

### S5 Analysis

**S5 confirms: fluctuating faults defeat all strategies.**

All strategies except fixed_isolation cluster tightly at 119-121ms (CI <1ms).
The system is deterministically saturated during fault-on periods.

fixed_isolation's lower mean (115.6) is pulled down by a single outlier run
(33.9ms, likely a seed where isolation triggered at the right phase). Its CI
of ±9.0 reflects this instability.

**Conclusion**: S5's fluctuating fault pattern at this intensity (3 nodes, 5x,
50% duty cycle) overwhelms all strategies. The scenario needs redesign (fewer
fault nodes, lower peak, or asymmetric duty cycle) to be discriminative.

## Implications for Research

1. **S4 is solved**: adaptive with theta_iso=0.5 matches fixed_isolation
2. **V8's "fixed_isolation >> adaptive" finding was a statistical artifact**
3. **S4's random slowdowns create inherent high variance** — consider fixed slowdowns
4. **S5 remains undiscriminative** — fundamental scenario design issue, not strategy
5. **P999 shows same pattern**: adaptive ≈ fixed_isolation for S4
