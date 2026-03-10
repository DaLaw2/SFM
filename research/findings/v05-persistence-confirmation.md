# V05 Findings: Persistence-Confirmed Peer-Comparison Detection

**Date**: 2026-03-08
**Baseline**: 76a37cb (V4)

## Context

V5 replaces V4's hybrid detection (peer-comparison + M/D/1 guard) with a
simpler persistence-confirmed approach, based on the V4 insight that the
S3/S6 tension is about transient-vs-persistent anomalies, not
conservative-vs-sensitive detection.

### V5: Persistence-Confirmed Detection (`detector.py`)
- Pure peer-comparison severity: `max(0, 1 - median/node_lat)`
- No M/D/1 guard — removed entirely
- Persistence check: severity only emitted after CONFIRM_EPOCHS=2 consecutive
  epochs where raw severity > MIN_SEVERITY (0.05)
- Transient noise (S3 overload) fluctuates → fails persistence check
- Permanent faults (S6 cascade) produce stable severity → passes quickly

## Key Result: S6 Fixed, S4 Regressed

V5 recovered V2-level performance on S6 (cascade) but lost V4's S4 gain.

## Cross-Version Comparison: Adaptive P99 Latency (ms)

| Scenario | no_mitig | V2 | V3 | V4 | V5 | Best |
|----------|----------|-----|-----|-----|-----|------|
| S2 Progressive | 70 | 33.7 | 34.3 | 34.1 | 35.0 | V2 |
| S3 Flash Crowd | 82 | 166.8 | 125.0 | 188.0 | 177.1 | V3 |
| S4 Multi-Node | 99 | 275.0 | 95.0 | 73.1 | 104.0 | V4 |
| S5 Fluctuating | 38 | 33.5 | 33.7 | 34.2 | 35.1 | V2 |
| S6 Cascade | 151 | 69.7 | 99.0 | 102.8 | 69.8 | V2/V5 |
| S7 Recovery | 38 | 32.1 | 31.7 | 32.2 | 34.4 | V3 |

## Cross-Version Comparison: SLO Violation Rate

| Scenario | no_mitig | V2 | V3 | V4 | V5 |
|----------|----------|-----|-----|-----|-----|
| S2 | 0% | 0% | 0% | 0% | 0% |
| S3 | 10-30% | 80% | 60% | 100% | 100% |
| S4 | 40-50% | 90% | 40% | 0% | 40% |
| S5 | 0% | 0% | 0% | 0% | 0% |
| S6 | 100% | 0% | 80% | 60% | 0% |
| S7 | 0% | 0% | 0% | 0% | 0% |

## V5 Full Results: P99 Latency (ms)

| Scenario | no_mitig | fixed_spec | fixed_shed | fixed_iso | adaptive |
|----------|----------|------------|------------|-----------|----------|
| S1 (s=3.0) | 99.7 | 54.2 | 53.2 | 56.8 | 60.7 |
| S1 (s=5.0) | 161.2 | 60.2 | 56.9 | 57.8 | 59.8 |
| S2 | 69.9 | 38.4 | 37.1 | 34.1 | 35.0 |
| S3 | 81.9 | 76.0 | 126.0 | 256.0 | 177.1 |
| S4 | 98.5 | 91.0 | 77.0 | 91.0 | 104.0 |
| S5 | 37.7 | 35.6 | 34.2 | 36.1 | 35.1 |
| S6 | 151.0 | 98.0 | 101.0 | 99.0 | 69.8 |
| S7 | 37.8 | 34.8 | 36.6 | 33.6 | 34.4 |

## Analysis

### Success: S6 Cascade Recovered

P99 = 69.8ms / 0% SLO violations — matches V2 (69.7ms / 0%).  The
persistence confirmation eliminates the M/D/1 guard's exponential blowup
problem at high rho.  Node 0 (5x slowdown at t=10) and node 1 (3x at t=30)
both produce sustained peer-comparison severity that passes the 2-epoch
confirmation window.

### Regression: S4 Multi-Node

P99 = 104ms (vs V4's 73ms).  Without the M/D/1 guard, peer-comparison
at 80% load produces some noise severity on healthy nodes.  The persistence
check filters most of it, but the detection profile changes.  V4's M/D/1
guard had an unintended benefit for S4: by filtering healthy-node noise, it
made faulty nodes stand out more clearly, producing higher relative severity
and more decisive strategy selection.

### S3 Flash Crowd Still Problematic

P99 = 177ms, similar to V4 (188ms).  Root cause unchanged: fault is
correctly detected at 70% load (peer-comparison produces sustained
severity → passes persistence check).  When load spikes to 95%, the
severity may drop but strategies persist due to selector de-escalation
delay (4 epochs / 2 seconds from SHED → NORMAL).

## Key Insight: Each Version Solves Different Scenarios Best

| Scenario | Best Version | Mechanism |
|----------|-------------|-----------|
| S4 | V4 (M/D/1 guard) | Guard filters healthy-node noise → faulty nodes stand out |
| S6 | V5 (persistence) | No guard blowup → peer-comparison catches gradual faults |
| S3 | V3 (unified baseline) | max(md1, median) baseline moderates severity |

This suggests V6 should combine:
- V5 persistence confirmation (fixes S6)
- V4 M/D/1 guard (fixes S4) — but with a rho cap to prevent blowup at high rho
- Or: variance-aware guard that replaces M/D/1 with peer dispersion

The rho-capped M/D/1 guard is simplest: use md1_expected * 1.4 as guard,
but cap rho at ~0.85 so guard_threshold never exceeds a reasonable value
(~54ms at rho=0.85 vs 124ms at rho=0.94).

## Remaining Research Gaps (V6 Candidates)

### G1: Persistence + Capped M/D/1 Guard
Combine V5 persistence with V4 M/D/1 guard, but cap rho at 0.85:
- guard_threshold = md1_expected(min(rho, 0.85)) * 1.4
- At rho < 0.85: guard active, filters noise (helps S4)
- At rho > 0.85: guard frozen at ~54ms, won't suppress real faults (helps S6)
- Persistence provides secondary filtering for transient noise

### G2: Fast De-escalation for Load Spikes
When spare_capacity drops below threshold, allow multi-step or immediate
de-escalation in selector.  Would help S3 by removing SHED faster when
load spikes.

### G3: Variance-Aware Guard
Use coefficient of variation (CV) of peer latencies instead of M/D/1:
- Low CV → uniform latency → suppress (probably load, not fault)
- High CV → outliers → allow detection

## Reproducibility

- Git commit: (pending)
- V4 baseline: commit 76a37cb
- Results: experiments/results/s1_severity_sweep/ through s7_recovery/
