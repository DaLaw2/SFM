# V12 Findings: Breaking-Point Analysis (S8)

**Date**: 2026-03-08
**Baseline**: 990d43c (V11)
**Experiment**: S8 — sweep fault fraction (4,8,12,16 of 32 nodes) × severity (3x,5x,10x,20x)

## Capacity Guard Fix

V11's severity-aware guard had a systematic flaw: it underestimated isolation
cost at moderate severity with many faults. Example: 8 nodes at 3x (severity=0.667):
- Guard computed: effective_cap_loss = 8×0.333 = 2.664, remaining_rho = 0.873 → APPROVE
- Actual remaining: 24 nodes at 100 req/s = 2400, demand = 2560 → rho = 1.067 → OVERLOAD

Fix: Added Layer 2 absolute capacity check. After isolation, remaining node count
must satisfy: `n_remaining >= (1-spare) × N / 0.92`. This prevents the severity-aware
formula from approving isolation that causes overload.

## S8 Results — Adaptive P99 (ms)

### V12 (with absolute capacity guard)
|  | 3x | 5x | 10x | 20x |
|---|---|---|---|---|
| 4 faults (12.5%) | **37.8 ✓** | **48.7 ✓** | 440.4 ✗ | **48.9 ✓** |
| 8 faults (25%) | 166.4 ✗ | 1035 ✗ | 17043 ✗ | 15652 ✗ |
| 12 faults (37.5%) | 6941 ✗ | 16783 ✗ | 29320 ✗ | 29783 ✗ |
| 16 faults (50%) | 15203 ✗ | 26027 ✗ | 36298 ✗ | 37907 ✗ |

### No Mitigation P99 (ms) — control
|  | 3x | 5x | 10x | 20x |
|---|---|---|---|---|
| 4 | 95.7 | 185.8 | 439.0 | 49.0 |
| 8 | 163.3 | 1045 | 17125 | 15720 |
| 12 | 6825 | 16821 | 29459 | 29785 |
| 16 | 15230 | 26010 | 36344 | 37861 |

### Capacity Guard Fix Impact (8-fault cases)
| Config | V11 (broken) | V12 (fixed) | no_mitig | V11 vs no_mitig |
|--------|-------------|-------------|----------|-----------------|
| 8/3x | 187.9 | 166.4 | 163.3 | +14% (worse) → ≈0% |
| 8/5x | 3657 | 1035 | 1045 | +321% (worse) → ≈0% |

## Key Findings

### 1. Capacity-Theoretic Fault Fraction Limit

At load factor L, with isolation threshold U, maximum tolerable fault fraction:

    max_fault_fraction = 1 - L/U

At L=0.80, U=0.92: **max = 13.0%**

Empirical validation: 4/32 = 12.5% passes (3 of 4 severities under SLO),
8/32 = 25% universally fails. The formula accurately predicts the boundary.

### 2. "Mitigation Worse Than Nothing" Regime — Fixed

V11 had a systematic flaw where adaptive was 4x worse than no_mitigation at
8/5x because the severity-aware guard approved isolation that caused overload.
V12's absolute capacity check eliminates this: adaptive now matches or equals
no_mitigation when isolation is infeasible.

### 3. Severity Non-Monotonicity (4/10x Anomaly)

P99 at 4/10x (440ms) >> P99 at 4/20x (49ms). Root cause:
- At 20x: P2C queue-depth signal is so strong that fault nodes are implicitly
  self-isolated. Only 0.78% of traffic reaches them (below P99 threshold of 1%).
- At 10x: P2C signal is weaker, 1.56% of traffic reaches fault nodes (above P99
  threshold). Those requests at 10× service time dominate P99.
- The "worst severity" is the one where affected_ratio just exceeds the
  percentile threshold: affected_ratio > (100% - percentile).

### 4. P2C as Implicit Mitigation

At extreme severity (20x+), P2C's queue-depth avoidance outperforms explicit
isolation strategies because it acts instantaneously (every request routing decision)
rather than after detection delay (1-1.5s). This suggests the optimal approach is
hybrid: use P2C natural avoidance for extreme faults, explicit isolation for
moderate faults (3x-5x) where P2C signal is weak.

### 5. Operating Envelope

The system's effective operating envelope for 80% load:
- **Green zone**: ≤4 faults at 3x-5x severity → P99 < 50ms, SLO viol < 1%
- **Yellow zone**: 4 faults at 10x OR 8 faults at 3x → P99 100-440ms
- **Red zone**: 8+ faults at 5x+ → system collapse (seconds to tens of seconds)

## Decision

Keep the V12 absolute capacity guard fix. It correctly prevents the "mitigation
worse than nothing" trap without regressing S4 or other scenarios. The S8
breaking-point experiment provides valuable data for understanding the system's
fundamental limits, which are capacity-theoretic, not algorithmic.
