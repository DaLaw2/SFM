# V04 Findings: Hybrid Detection (Peer-Comparison + M/D/1 Guard)

**Date**: 2026-03-08
**Baseline**: 38963ef (V3)

## Context

V4 implements G1-revised hybrid detection in `detector.py` to address the
V3 regression in S6 (cascade) while preserving S3/S4 improvements:

### G1-revised: Hybrid Detection (`detector.py`)
- Primary: peer-comparison severity = `max(0, 1 - median/node_lat)` (V2-style)
- Guard: suppress severity when `node_lat <= md1_expected * 1.4` (V3-style)
- Goal: peer-comparison sensitivity for gradual faults (S6) + M/D/1 guard
  for overload noise suppression (S3)

No changes to selector.py, monitor.py, or other components.

## Key Result: S4 Improved, S3 Regressed, S6 Unchanged

V4 improved S4 further but caused significant S3 regression and failed to
fix S6. Net: **5/7 scenarios where adaptive helps or is neutral** (vs 6/7 V3).

## V3 vs V4 Comparison: Adaptive P99 Latency (ms)

| Scenario | no_mitig | V3 adaptive | V4 adaptive | Change |
|----------|----------|-------------|-------------|--------|
| S2 Progressive (80%) | 70.4 | 34.3 | 34.1 | ~same |
| S3 Flash Crowd (70-95%) | 82-89 | 125.0 | **188.0** | +50% regression |
| S4 Multi-Node (80%) | 99.0 | 95.0 | **73.1** | -23%, best yet |
| S5 Fluctuating (80%) | 37.7 | 33.7 | 34.2 | ~same |
| S6 Cascade (85%) | 151.0 | 99.0 | 102.8 | ~same (not fixed) |
| S7 Recovery (80%) | 37.7 | 31.7 | 32.2 | ~same |

## V3 vs V4 Comparison: SLO Violation Rate

| Scenario | no_mitig | V3 adaptive | V4 adaptive |
|----------|----------|-------------|-------------|
| S2 | 0% | 0% | 0% |
| S3 | 10-30% | 60% | **100%** |
| S4 | 40-50% | 40% | **0%** |
| S5 | 0% | 0% | 0% |
| S6 | 100% | 80% | 60% |
| S7 | 0% | 0% | 0% |

## V4 Full Results: P99 Latency (ms)

| Scenario | no_mitig | fixed_spec | fixed_shed | fixed_iso | adaptive |
|----------|----------|------------|------------|-----------|----------|
| S1 (s=3.0) | 99.8 | 54.2 | 53.2 | 56.8 | 65.7 |
| S1 (s=5.0) | 158.6 | 60.2 | 56.9 | 57.8 | 55.7 |
| S2 | 70.4 | 38.4 | 37.1 | 34.1 | 34.1 |
| S3 | 89.0 | 76.0 | 126.0 | 256.0 | 188.0 |
| S4 | 99.9 | 91.0 | 77.0 | 91.0 | 73.1 |
| S5 | 37.7 | 35.6 | 34.2 | 36.1 | 34.2 |
| S6 | 152.1 | 98.0 | 101.0 | 99.0 | 102.8 |
| S7 | 37.8 | 34.8 | 36.6 | 33.6 | 32.2 |

## Root Cause Analysis

### S3 Regression: Severity Inflation + De-escalation Delay

Full causal chain:

1. **Severity inflation**: V4 uses `median` as denominator; V3 used
   `max(md1, median)`. At 70% load, md1 > median, so V4 severity is higher
   (0.37 vs 0.29 for typical fault node).
2. **Strategy escalation**: Higher severity pushes V4 into SHED at 70% load;
   V3 only reached SPECULATE.
3. **De-escalation delay**: When load spikes to 95%, severity drops to 0
   (guard activates), but SHED requires 4 epochs (2s) to de-escalate to
   NORMAL (debounce=2, single-step). V3's SPECULATE only needed 2 epochs (1s).
4. **Capacity collapse**: SHED at 95% load with weight=0.63 on faulty node
   pushes healthy nodes from rho=0.95 to rho=0.97. M/D/1 nonlinearity:
   latency jumps from 105ms to 184ms (+75%).

### S6 Non-improvement: M/D/1 Guard Exponential Blowup

The M/D/1 guard threshold scales as `1/(1-rho)`, which explodes near
saturation:

| Period | rho | V4 guard (md1*1.4) | V2 guard (median*ratio) |
|--------|-----|--------------------|-----------------------|
| t<10 (no fault) | 0.85 | 53.7ms | 48ms |
| t=10-30 (1 fault) | 0.90 | 77ms | 61ms |
| t>30 (2 faults) | 0.94 | **124ms** | **70ms** |

At t>30, V4 guard (124ms) exceeds SLO target (100ms). Node 1's 3x slowdown
may produce P99 below 124ms at high load, causing the guard to suppress
detection entirely. V2's median-based guard (70ms) is anchored to observed
healthy-node latency, avoiding exponential blowup.

Positive feedback loop: fault → spare↓ → rho↑ → guard↑ → detection
suppressed → fault continues receiving traffic → latency worsens.

## Insight: M/D/1 Guard Is Fundamentally Flawed at High rho

The M/D/1 mean sojourn time `t_base + rho*t_base/(2*(1-rho))` diverges as
rho → 1. Using it as a guard threshold means:
- At moderate load (rho < 0.8): works well, suppresses noise
- At high load (rho > 0.9): guard threshold exceeds SLO, suppresses real faults

The S3 vs S6 tension is NOT about conservative vs sensitive detection.
It's about **transient vs persistent** anomalies:
- S3: high latency is transient (load spike), fluctuates between epochs
- S6: high latency is persistent (permanent fault), stable across epochs

## Candidate Approaches for V5

### A: Variance-Aware Guard
Replace M/D/1 guard with peer-dispersion check (CV or IQR):
- Low CV (all nodes similar) → high guard → suppress (S3) ✓
- High CV (outlier nodes) → low guard → detect (S6) ✓
- Medium complexity, needs CV threshold tuning

### B: Per-Node M/D/1
Compute M/D/1 expected per node using per-node throughput and P50.
- Risk: faulted node's per-node rho also high → may still suppress
- High complexity

### C: Persistence Confirmation (Recommended)
Remove M/D/1 guard entirely. Pure peer-comparison + K-epoch consecutive
confirmation:
- severity = max(0, 1 - median/node_lat) [always computed]
- Only emit confirmed severity after K consecutive epochs with sev > threshold
- S3: transient noise → not sustained K epochs → filtered ✓
- S6: permanent fault → sustained → confirmed ✓
- Low complexity, leverages fundamental transient-vs-persistent distinction
- K=2-3 epochs (1-1.5s) is small relative to 90s simulation

### D: Hybrid C+A
Combine persistence confirmation with lightweight variance guard as
secondary filter for additional robustness.

## Reproducibility

- Git commit: (pending)
- V3 baseline: tag v3-md1-detection (commit 38963ef)
- Results: experiments/results/s1_severity_sweep/ through s7_recovery/
