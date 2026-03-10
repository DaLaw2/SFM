# V10 Findings: S5 Fluctuating Fault — 2 Node Fix

**Date**: 2026-03-08
**Baseline**: e44ee8f (V6-final)

## Context

V10 statistical validation (20 runs) showed S5 with 3 fault nodes was completely
undiscriminative — all strategies at 119-121ms P99 (CI <1ms). System was saturated
during fault-on periods (rho=0.865, above M/D/1 nonlinear knee at ~0.85).

Hypothesis: reducing to 2 fault nodes (rho=0.842 during fault-on) would cross below
the saturation threshold and allow strategy differentiation.

## S5 Results (2 fault nodes, 32 workers, 80% load, 5x 8s/8s, 20 runs)

### P99 Latency (ms)
| Baseline | Mean | 95% CI | Range |
|----------|------|--------|-------|
| **fixed_isolation** | **30.7** | **±0.18** | 30.1 - 31.7 |
| **adaptive** | **31.0** | **±0.49** | 30.4 - 35.4 |
| no_mitigation | 35.6 | ±0.09 | 35.2 - 36.1 |
| fixed_shedding | 35.9 | ±1.74 | 30.3 - 43.0 |
| fixed_speculation | 38.3 | ±2.36 | 30.5 - 47.2 |

### P999 Latency (ms)
| Baseline | Mean | 95% CI | Range |
|----------|------|--------|-------|
| **fixed_isolation** | **38.0** | **±0.10** | 37.7 - 38.5 |
| **adaptive** | **43.4** | **±11.6** | 37.6 - 149.2 |
| fixed_shedding | 127.5 | ±23.9 | 37.9 - 176.1 |
| fixed_speculation | 140.2 | ±28.3 | 37.8 - 177.2 |
| no_mitigation | 173.7 | ±0.84 | 170.7 - 176.9 |

### SLO Violation Rate (50ms target)
| Baseline | Mean |
|----------|------|
| fixed_isolation | 0.016% |
| adaptive | 0.038% |
| fixed_shedding | 0.48% |
| fixed_speculation | 0.62% |
| no_mitigation | 0.80% |

### Goodput (req/s)
| Baseline | Mean | CI |
|----------|------|----|
| adaptive | 2559.3 | ±2.4 |
| fixed_isolation | 2557.4 | ±3.1 |
| fixed_shedding | 2547.3 | ±4.0 |
| fixed_speculation | 2544.4 | ±4.9 |
| no_mitigation | 2539.5 | ±2.2 |

### Affected Ratio (requests served by fault nodes)
| Baseline | Mean |
|----------|------|
| fixed_isolation | 0.016% |
| adaptive | 0.17% |
| fixed_shedding | 2.26% |
| fixed_speculation | 2.83% |
| no_mitigation | 3.87% |

## Analysis

### Success: S5 is now discriminative

From 3-node undiscriminative (all ~120ms) to clear 3-tier separation:
1. **Tier 1**: fixed_isolation ≈ adaptive (~31ms P99, <0.04% SLO violation)
2. **Tier 2**: no_mitigation ≈ fixed_shedding (~36ms P99)
3. **Tier 3**: fixed_speculation (~38ms P99)

P999 shows even clearer separation: 38ms → 43ms → 128-140ms → 174ms.

### Saturation threshold confirmed

- 3 fault nodes: rho_on = 2560/2960 = 0.865 → saturated, no discrimination
- 2 fault nodes: rho_on = 2560/3040 = 0.842 → below knee, strategies differentiate
- M/D/1 nonlinear knee at rho ≈ 0.85 confirmed as critical boundary

### P99 paradox: no_mitigation beats fixed_shedding

no_mitigation (35.6ms) ≈ fixed_shedding (35.9ms) at P99 (Welch t-test p > 0.5).
P2C's implicit avoidance (shortest-queue selection) naturally avoids slow nodes.
SHED weight damping at 80% load (spare_factor ≈ 0.8) nearly suppresses the weight
adjustment, making SHED ~equivalent to no_mitigation at the median case.

But at P999: fixed_shedding (127.5ms) << no_mitigation (173.7ms). SHED's residual
weight reduction helps the worst-case tail even when nearly damped.

### Adaptive P999 variance concern

adaptive P999 CI is ±11.6ms (vs fixed_isolation's ±0.10ms). Root cause: strategy
switching transients. Each fault on/off transition has ~1s detection/confirmation
delay (CONFIRM_EPOCHS=2 × 500ms epoch). During this window, protection is incomplete.
The escalation ladder (SPECULATE→SHED→ISOLATE) introduces additional switching delay
that fixed_isolation avoids with "one-step" isolation.

### fixed_speculation worst at P99

Surprising: speculation performs worse than no_mitigation. Likely cause: hedge
requests at 80% load consume spare capacity, competing with normal requests.
The speculation overhead outweighs its benefit when fault nodes are already
mostly avoided by P2C.

## Expert Consensus: Next Steps

1. **Priority 1**: Reduce adaptive switching transient — consider "hold isolation"
   mechanism (minimum isolation duration to avoid oscillation during fluctuating faults)
2. **Priority 2**: Review SHED weight damping at 80% load — currently too aggressive,
   making SHED ≈ no_mitigation at P99
3. **Priority 3**: Run full S1-S7 suite to verify no regressions from S5 parameter change
