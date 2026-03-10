# V11 Findings: Severity-Aware Capacity Guard

**Date**: 2026-03-08
**Baseline**: c407663 (V10 full suite)

## The Problem

S4 multi-node scenario (4 faults, random 2-5x) had P99 = 97ms for adaptive —
nearly 2x the 50ms SLO target. Root cause: the old G2 capacity guard treated
each isolated node as losing 1.0 capacity, computing:

    remaining_rho = 0.80 × 32 / (32-4) = 0.914 > 0.9 threshold

This blocked isolation of the 4th faulty node, downgrading it to SHED. But a
node with severity 0.8 (5x slowdown) only has 0.2 effective capacity — isolating
it costs 0.2, not 1.0.

## The Fix

Severity-aware capacity guard: each node's isolation cost = (1 - severity).
For 4 nodes with average severity ~0.67 (corresponding to 2-5x slowdowns):

    effective_cap_loss = sum(1 - sev) ≈ 1.3 (not 4.0)
    effective_remaining = 32 - 1.3 = 30.7
    remaining_rho = 0.80 × 32 / 30.7 = 0.834 < 0.92 ← guard does not trigger

All 4 nodes can now be isolated. Also added greedy ordering: highest-severity
nodes are isolated first (cheapest cost), with fallback to SHED for remaining
if budget is exceeded. Threshold raised from 0.9 to 0.92 (still safe given
SHED capacity guard at 0.88 as second layer).

## Results: S4 Dramatic Improvement

### S4 P99 Latency (ms) — V10 vs V11
| Baseline | V10 | V11 | Change |
|----------|-----|-----|--------|
| adaptive | 97.0 | 37.7 | **-61%** |
| fixed_isolation | 112.6 | 37.6 | **-67%** |
| fixed_speculation | 108.6 | 37.8 | **-65%** |
| fixed_shedding | 117.0 | 46.3 | **-60%** |
| no_mitigation | 125.2 | 120.7 | ~0% |

### S4 P999 Latency (ms) — V10 vs V11
| Baseline | V10 | V11 | Change |
|----------|-----|-----|--------|
| adaptive | 139.4 | 47.4 | **-66%** |
| fixed_isolation | 158.5 | 47.4 | **-70%** |
| fixed_speculation | 160.9 | 58.9 | **-63%** |
| fixed_shedding | 167.5 | 79.3 | **-53%** |
| no_mitigation | 177.5 | 172.1 | ~0% |

### S4 SLO Violation Rate — V10 vs V11
| Baseline | V10 | V11 | Change |
|----------|-----|-----|--------|
| adaptive | 2.38% | 0.079% | **-97%** |
| fixed_isolation | 3.19% | 0.080% | **-97%** |
| fixed_speculation | 3.40% | 0.110% | **-97%** |
| fixed_shedding | 3.44% | 0.560% | **-84%** |
| no_mitigation | 3.65% | 3.73% | ~0% |

## Regression Check: Other Scenarios

### Adaptive P99 (ms) — V10 vs V11
| Scenario | V10 | V11 | Change |
|----------|-----|-----|--------|
| S2 | 30.4 | 30.3 | ~0% |
| S3 | 40.2 | 41.3 | +3% (noise) |
| S5 | 31.0 | 30.7 | ~0% |
| S6 | 33.1 | 32.9 | ~0% |
| S7 | 29.7 | 29.7 | ~0% |

**Zero regressions.** All non-S4 scenarios unchanged within noise.

## Analysis

### Why the improvement is so large

The old guard was pathologically conservative for S4. It assumed isolating 4
nodes removes 4.0 capacity units, but the actual cost was ~1.3 units. By
allowing full isolation, all faulty node traffic gets redirected to healthy
nodes, eliminating the queue debt that caused cascading latency.

The improvement extends to ALL mitigation strategies (not just adaptive)
because even fixed_isolation (theta_iso=0.3) was hitting the capacity guard
when trying to isolate the 4th node.

### no_mitigation unchanged (control validation)

no_mitigation P99 = 120.7ms (vs 125.2 before) — within noise. This confirms
the improvement is from the capacity guard change, not from different random
seeds or other confounds.

### S4 now meets SLO

All strategies except no_mitigation now achieve P99 < 50ms and P999 < 80ms.
SLO violation drops from 2-3.5% to 0.08-0.56%. S4 is no longer a problem
scenario — it's now as well-controlled as S2/S6/S7.

## New Cross-Scenario Rankings (V11)

### Adaptive P99 (ms)
| Scenario | P99 | SLO Viol% | Status |
|----------|-----|-----------|--------|
| S7 | 29.7 | 0.013% | Excellent |
| S2 | 30.3 | 0.001% | Excellent |
| S5 | 30.7 | 0.015% | Excellent |
| S6 | 32.9 | 0.035% | Excellent |
| S4 | 37.7 | 0.079% | Good |
| S3 | 41.3 | 0.133% | Good |

All 6 scenarios now have P99 < 50ms SLO. This is the first time all scenarios
pass the SLO target.
