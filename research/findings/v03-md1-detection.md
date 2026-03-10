# V03 Findings: M/D/1 Baseline Detection + Capacity-Aware Isolation

**Date**: 2026-03-08
**Baseline**: 4caff9e (V2)

## Context

V3 implements two modifications to address the remaining 2/7 problem scenarios
from V2 (S3 flash crowd, S4 multi-node):

### G1: M/D/1 Baseline Detection (`detector.py`)
- Replaces V2's peer-comparison (median-based) severity with queueing theory baseline
- `baseline = max(M/D/1_mean_sojourn(rho), median_p99)`
- At high load, M/D/1 mean dominates → prevents false positives from queueing noise
- At low load, median dominates → preserves peer-comparison sensitivity
- MIN_FAULT_RATIO = 1.4: node must exceed baseline by 40% to be flagged
- rho derived from spare_capacity: `rho = 1 - spare_capacity`

### G2: Capacity-Aware Isolation (`selector.py`)
- Replaced V2's fixed isolation fraction with dynamic capacity check
- Before allowing isolation, estimates remaining utilization: `rho_remaining = (1-spare) * N / (N-K)`
- If `rho_remaining > 0.9`, limits isolation count to prevent capacity collapse
- Excess nodes downgraded from ISOLATE to SHED (sorted by severity, highest kept)

### Development Note: G2 Tuning Was Critical

First G2 implementation used a fixed budget (N/4 = 4 nodes). This caused
**catastrophic failure** in S3 (P99 3449ms) and S4 (P99 3131ms) because:
- S4: isolating 4/16 nodes at 80% load → remaining 12 nodes at 107% utilization → queue explosion
- S3: during 95% spike, even 1 isolated node pushes remaining 15 to 101% → cascade

The capacity-aware approach solved S4 completely and reduced S3 damage.

## Key Result: S3/S4 Improved, S6 Regressed

V3 fixed the two target scenarios but introduced a regression in S6 (cascade).
Net: **6/7 scenarios where adaptive helps or is neutral** (vs 5/7 in V2).

## V2 vs V3 Comparison: Adaptive P99 Latency (ms)

| Scenario | no_mitig | V2 adaptive | V3 adaptive | Change |
|----------|----------|-------------|-------------|--------|
| S2 Progressive (80%) | 70.1 | 33.7 | 34.3 | ~same |
| S3 Flash Crowd (70-95%) | 81.3 | 166.8 | **125.0** | -25%, still worse than no_mitig |
| S4 Multi-Node (80%) | 98.3 | 275.0 | **95.0** | **-65%, now beats no_mitig!** |
| S5 Fluctuating (80%) | 37.5 | 33.5 | 33.7 | ~same |
| S6 Cascade (85%) | 150.9 | **69.7** | 99.0 | +42% regression |
| S7 Recovery (80%) | 37.6 | 32.1 | 31.7 | ~same |

## V2 vs V3 Comparison: SLO Violation Rate

| Scenario | no_mitig | V2 adaptive | V3 adaptive |
|----------|----------|-------------|-------------|
| S2 | 0% | 0% | 0% |
| S3 | 10% | 80% | **60%** |
| S4 | 40% | 90% | **40%** (matches no_mitig) |
| S5 | 0% | 0% | 0% |
| S6 | 100% | **0%** | 80% (regressed) |
| S7 | 0% | 0% | 0% |

## V3 Full Results: P99 Latency (ms)

| Scenario | no_mitig | fixed_spec | fixed_shed | fixed_iso | adaptive |
|----------|----------|------------|------------|-----------|----------|
| S1 (s=3.0) | 100.0 | 54.2 | 53.2 | 56.8 | 62.0 |
| S1 (s=5.0) | 155.8 | 60.2 | 56.9 | 57.8 | 58.0 |
| S2 | 70.4 | 38.4 | 37.1 | 34.1 | 34.3 |
| S3 | 82.0 | 76.0 | 126.0 | 256.0 | 125.0 |
| S4 | 99.0 | 91.0 | 77.0 | 91.0 | 95.0 |
| S5 | 37.7 | 35.6 | 34.2 | 36.1 | 33.7 |
| S6 | 151.0 | 98.0 | 101.0 | 99.0 | 99.0 |
| S7 | 37.7 | 34.8 | 36.6 | 33.6 | 31.7 |

## V3 Full Results: SLO Violation Rate

| Scenario | no_mitig | fixed_spec | fixed_shed | fixed_iso | adaptive |
|----------|----------|------------|------------|-----------|----------|
| S2 | 0% | 0% | 0% | 0% | 0% |
| S3 | 10% | 0% | 60% | 100% | 60% |
| S4 | 50% | 30% | 10% | 40% | 40% |
| S5 | 0% | 0% | 0% | 0% | 0% |
| S6 | 100% | 40% | 70% | 60% | 80% |
| S7 | 0% | 0% | 0% | 0% | 0% |

## Analysis

### Success: S4 Multi-Node

V3 adaptive P99 = 95ms vs no_mitig 99ms — **first time adaptive beats no_mitigation
in this scenario**. The capacity-aware isolation budget prevents the cascade
failure that plagued V2 (275ms). When isolating nodes would push remaining
workers above 90% utilization, excess isolation is downgraded to SHED.

### Improvement: S3 Flash Crowd

P99 dropped from 166.8ms (V2) to 125ms (V3), and SLO violations from 80% to
60%. Still worse than no_mitig (82ms, 10%). Root cause: at 70% load the
detector correctly identifies the fault and activates SHED. When load spikes to
95%, the SHED strategy's hedging (1412 hedges observed) adds overhead. The
M/D/1 baseline correctly suppresses false positives at 95% load, but strategies
activated at 70% persist through the spike due to hysteresis/debounce.

### Regression: S6 Cascade

V3 adaptive regressed from P99 69.7ms / 0% SLO (V2) to 99ms / 80% SLO (V3).
Root cause: G1's M/D/1 baseline raises the detection threshold, making the
detector less sensitive to gradual cascading faults. The cascade starts mild
(slowdown 1.5x) and escalates (to 3x). V2's peer-comparison (median-based)
detector caught the early stages; G1's higher baseline misses them until the
fault is severe.

This reveals a fundamental tension:
- **G1 (M/D/1 baseline)**: conservative, good for high-load false positive suppression
- **V2 M5 (peer comparison + load-aware ratio)**: sensitive, good for gradual faults

### Insight: Need Hybrid Detection

The optimal detector should combine both approaches:
- Use peer comparison (median-based) as the primary detection method
- Use M/D/1 baseline as a **guard**: suppress detection only when observed
  latency is explainable by the current load level alone
- This preserves sensitivity to gradual faults (S6) while preventing false
  positives at high load (S3)

## Remaining Research Gaps (V4 Candidates)

### G1-revised: Hybrid Detection
Combine V2 peer-comparison with G1 M/D/1 guard:
- severity = max(0, 1 - median/node_lat) [V2 formula]
- BUT: zero out severity if node_lat <= M/D/1_expected * threshold [G1 guard]
- This keeps peer sensitivity for cascades while suppressing overload noise

### S3 Strategy Persistence
SHED strategy with hedging persists through load spikes due to
hysteresis/debounce. Need faster de-escalation when spare_capacity drops
suddenly (spike detection in the control loop).

### S6 Detection Sensitivity
Even with hybrid detection, may need severity EMA (G5 from earlier analysis)
to smooth detection for gradual faults and prevent oscillation.

## Reproducibility

- Git commit: (pending)
- V2 baseline: tag v2-load-aware (commit 4caff9e)
- Results: experiments/results/s1_severity_sweep/ through s7_recovery/
