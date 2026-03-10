# V06 Findings: Departure Interval Service Time Estimation

**Date**: 2026-03-08
**Baseline**: 9fb1ea1 (V5)

## Context

V6 replaces all previous P99-based detection with departure interval service
time estimation — a load-invariant detection signal based on M/D/1 queueing
theory.

### V6: Departure Interval Detection (`detector.py`)
- Collect inter-departure intervals per node per epoch (sorted end_times)
- Take P10 of intervals as service time estimate (d_est)
- severity = max(0, 1 - t_base / d_est)
- Persistence confirmation retained (CONFIRM_EPOCHS=2)
- MIN_INTERVALS=5 required for estimation

### V6: Monitor Changes (`monitor.py`)
- NodeMetrics gains `departure_intervals` field
- Monitor computes intervals from sorted request end_times per epoch

## Key Result: Load-Invariant Detection Confirmed, Strategy Problem Proven

V6 confirms departure interval detection is load-invariant as predicted.
But this is a double-edged sword: at 95% load (S3), the detector correctly
identifies the fault → SHED never de-escalates → capacity collapse.

**This definitively proves S3 is a strategy problem, not a detection problem.**

## V6 Results: Adaptive P99 Latency (ms)

| Scenario | no_mitig | V5 | V6 | Change vs V5 |
|----------|----------|-----|-----|---------------|
| S2 Progressive | 70 | 35.0 | 33.8 | slightly better |
| S3 Flash Crowd | 85 | 177 | **209** | worse (expected) |
| S4 Multi-Node | 97 | 104 | **122** | worse |
| S5 Fluctuating | 38 | 35.1 | 33.6 | slightly better |
| S6 Cascade | 152 | 69.8 | 80.4 | slightly worse, 0% SLO |
| S7 Recovery | 38 | 34.4 | 32.2 | slightly better |

## V6 Full Results: P99 Latency (ms)

| Scenario | no_mitig | fixed_spec | fixed_shed | fixed_iso | adaptive |
|----------|----------|------------|------------|-----------|----------|
| S1 (s=3.0) | 98.6 | 54.2 | 53.2 | 56.8 | 55.8 |
| S1 (s=5.0) | 156.2 | 60.2 | 56.9 | 57.8 | 58.4 |
| S2 | 70.7 | 38.4 | 37.1 | 34.1 | 33.8 |
| S3 | 84.8 | 76.0 | 126.0 | 256.0 | 209.0 |
| S4 | 97.3 | 91.0 | 77.0 | 91.0 | 121.9 |
| S5 | 37.7 | 35.6 | 34.2 | 36.1 | 33.6 |
| S6 | 152.4 | 98.0 | 101.0 | 99.0 | 80.4 |
| S7 | 37.7 | 34.8 | 36.6 | 33.6 | 32.2 |

## V6 SLO Violation Rate

| Scenario | no_mitig | adaptive |
|----------|----------|----------|
| S2 | 0% | 0% |
| S3 | 20% | 90% |
| S4 | 30% | 80% |
| S5 | 0% | 0% |
| S6 | 100% | **0%** |
| S7 | 0% | 0% |

## Analysis

### S3 Regression: Correct Detection Causes Harm

Departure intervals detect the 2x fault at BOTH 70% and 95% load (d_est=20ms,
severity=0.5). Unlike P99-based detection (where severity naturally drops at
high load because all nodes are slow), departure intervals are load-invariant.

Result: SHED never de-escalates at 95% load. Weight=0.5 on faulty node pushes
healthy nodes from rho=0.95 to rho=0.97 → M/D/1 latency jumps 75%.

**Key insight: a more accurate detector made S3 worse.** This is the definitive
proof that S3 is a strategy/control problem.

### S4 Regression: SHED Oscillation Under Low Traffic

4/16 nodes detected with severity≈0.5 → weight=0.5 → healthy nodes at
rho≈1.07 (overloaded). Additionally, SHED reduces faulty node traffic so much
that departure intervals become unreliable (idle gaps dominate), causing
detection oscillation: detect → SHED → low traffic → insufficient data →
severity drops → de-escalate → traffic returns → detect again.

### S6 Slightly Worse Than V5 (80ms vs 70ms)

P10 percentile may be slightly conservative for cascade detection. Still
achieves 0% SLO violations, which is the important metric.

## Expert Discussion: V6 Post-Mortem

Three expert panels (queueing theory, control systems, distributed systems)
analyzed V6 results. Full discussion in insights-v6-expert-discussion.md.

### Unanimous Conclusions
1. Stop modifying the detector — V6 departure intervals are theoretically correct
2. S3 requires a strategy-layer fix (mitigation budget), not better detection
3. S4 needs capacity-aware SHED protection (extend G2 pattern to SHED)

### Key Theoretical Finding (Queueing Theory Expert)
The current SHED weight formula `w = 1 - severity = t_base/d_est` is already
mathematically equivalent to the theoretically optimal static routing weight
(`w_i ∝ 1/d_i` where d_i is service time). The problem is not the weight
formula but the lack of capacity constraints.

### Recommended V6-final Changes
1. SHED weight damping: `spare_factor = (spare-0.08)/0.15`, weight blended
   toward 1.0 at high load
2. SHED capacity guard: limit total weight reduction when healthy rho > 0.88
3. Apply at actuator (SHED weight), NOT at detector output — preserve detection
   truth for logging/AIMD/alerting

## Cross-Version Best Results

| Scenario | Best Version | P99 | Mechanism |
|----------|-------------|-----|-----------|
| S2 | V6 | 34ms | Departure interval + persistence |
| S3 | V3 | 125ms | Unified M/D/1 baseline (still bad) |
| S4 | V4 | 73ms | M/D/1 guard filtered noise |
| S5 | V6 | 34ms | Departure interval |
| S6 | V5 | 70ms | Persistence confirmation |
| S7 | V6 | 32ms | Departure interval |

## Reproducibility

- Git commit: (pending)
- V5 baseline: commit 9fb1ea1
- Results: experiments/results/s1_severity_sweep/ through s7_recovery/
