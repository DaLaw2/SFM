# V06 Discussion: Departure Interval Results Analysis

**Date**: 2026-03-08
**Context**: V6 departure interval estimation works but S3/S4 regressed, confirming S3 is purely a strategy problem.

## Queueing Theory Expert

### S4 Regression Root Cause
SHED reduces faulty node traffic → idle gaps dominate departure intervals →
d_est estimation becomes unreliable → detection oscillates between epochs.
At rho=0.8 with 4 nodes at weight=0.5, healthy nodes pushed to rho≈1.07.

**Proposed fixes:**
- Raise w_min from 0.05 to 0.15-0.20 (ensure enough traffic for reliable estimation)
- Filter idle gaps: exclude intervals > 2*median(intervals) before computing P10

### S6 Slightly Worse (80ms vs V5's 70ms)
P10 percentile is conservative during cascade onset — the fastest 10% of
departures may still reflect pre-fault service times. Suggested P25 with
lower MIN_SEVERITY, but acknowledged 10ms gap may be statistical noise.

### Critical Mathematical Finding
`1 - severity = 1 - (1 - t_base/d_est) = t_base/d_est`

This equals `μ_i / μ_base` — the theoretically optimal static routing weight
for heterogeneous M/D/1 queues. The current SHED weight formula IS the optimal
weight allocation (up to normalization). The problem is purely about capacity
constraints, not the weight formula.

### Mitigation Budget Justification
The linear formula `budget = (spare - 0.08) / 0.15` approximates the
queueing-theoretic condition: don't redistribute traffic when healthy nodes
would exceed a critical utilization (~0.92). Suggested raising lower bound
from 0.08 to 0.10-0.12. The ramp range 0.15 is reasonable.

### Bold Proposal: Eliminate Discrete Strategies
Since `w = t_base/d_est` is optimal, replace SPECULATE/SHED/ISOLATE with
continuous weight allocation + capacity constraint. This eliminates threshold
tuning entirely. Acknowledged as V7+ scope.

## Control Systems Expert

### Where to Apply Budget — Option (c) Recommended
Four options analyzed:

**(a) Detector output** (`severity *= budget`): Pollutes detection truth.
AIMD, logging, future alerting all need real severity. **Not recommended.**

**(b) Selector thresholds** (raise thresholds at high load): Global switch,
can't distinguish "high load no fault" from "high load severe fault."
**Risky for S6.**

**(c) SHED weight damping**: `weight = raw_weight * spare_factor + 1.0 * (1 - spare_factor)`.
Preserves detection truth, only dampens actuator force. **Recommended.**

**(d) All of the above**: Nonlinear interactions make behavior hard to reason
about. Occam's Razor. **Not recommended.**

### S4 Fix: Global SHED Capacity Constraint
After computing all SHED weights, calculate projected healthy-node rho.
If rho > 0.88, proportionally raise all SHED weights until safe. This extends
the G2 isolation budget pattern to SHED.

### Asymmetric EMA No Longer Needed
With SHED weight damping, EMA lag consequences are greatly reduced. Even if
spare is slightly overestimated during a few epochs, the weight damping still
provides strong suppression. Keep symmetric α=0.3.

### Feed-Forward with d_est
Since `1 - severity = t_base/d_est` is already the optimal weight, there's
no mathematical benefit to computing weights from d_est directly vs via
severity. The discrete strategy layer adds hysteresis/debounce which has
value for stability. Recommend keeping it for V6, consider removing in V7+.

## Distributed Systems Expert

### The Definitive Argument to Stop Iterating on Detection
Six versions, five different detection methods, S3 never solved:
- V2 load-aware: 167ms
- V3 M/D/1 baseline: 125ms
- V4 hybrid: 188ms
- V5 persistence: 177ms
- V6 departure intervals: 209ms

**The more accurate the detector, the worse S3 gets.** This is the strongest
possible evidence that detection cannot solve S3.

### Mitigation Budget Is One Line of Code
```python
budget = max(0.0, min(1.0, (metrics.spare_capacity - 0.08) / 0.15))
severities = {wid: sev * budget for wid, sev in severities.items()}
```
Preserves all existing strategy logic, just attenuates input signal at high load.

(Note: control expert disagrees on placement — prefers SHED weight damping
over severity attenuation to preserve detection truth. Both achieve similar
end results.)

### S4 Additional Fix: Aggregate SHED Capacity Guard
When multiple nodes are simultaneously SHED, limit total weight reduction.
Similar to existing G2 isolation budget but for SHED. Calculate remaining
effective capacity after SHED weights applied; if below threshold, scale
back SHED severity proportionally.

### Paper Narrative Update
V6 enables the strongest narrative yet:

**"Load-invariant detection is necessary but not sufficient. Precise fault
diagnosis combined with incorrect treatment is worse than no treatment at
all. The critical missing piece is load-aware strategy modulation — knowing
WHEN to act on detected faults, not just WHETHER faults exist."**

This frames the V1-V6 journey as systematic design space exploration:
- Detection dimension: latency-based → queueing-theory → service-time estimation
- Strategy dimension: fixed → adaptive → load-aware budget (V6-final)
- The insight: these dimensions are orthogonal; optimizing detection alone
  cannot solve strategy problems

### V6-final Minimum Viable Changes
1. SHED weight damping with spare_factor (fixes S3)
2. SHED capacity guard for multi-node (fixes S4)
3. Do NOT change detector, EMA, or de-escalation logic

## Cross-Expert Agreement Matrix

| Topic | QT Expert | CS Expert | DS Expert |
|-------|-----------|-----------|-----------|
| Stop changing detector | ✓ | ✓ | ✓ |
| S3 is strategy problem | ✓ | ✓ | ✓ |
| Need capacity constraint | ✓ | ✓ | ✓ |
| Budget at SHED weight | ✓ (continuous weights) | ✓ (option c) | prefers severity |
| Discrete strategies needed | No (remove in V7) | Yes (keep for stability) | Yes (too risky to remove) |
| Asymmetric EMA needed | Not discussed | No (budget suffices) | Not discussed |
| w=1-severity is optimal | ✓ (proven) | ✓ (noted equivalence) | Noted |
