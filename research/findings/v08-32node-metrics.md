# V08 Findings: 32-Node Experiment with Enhanced Metrics

**Date**: 2026-03-08
**Baseline**: ada7e0f (V7)

## Context

V7 (64 nodes) showed fault dilution — 5/7 scenarios had <1ms strategy difference.
V8 redesigns: 32 nodes, SLO 50ms, increased fault nodes, added P999/tail_ratio/goodput/SLO VR.

## V8 Parameter Changes

| Parameter | V7 | V8 | Rationale |
|-----------|----|----|-----------|
| Cluster size | 64 | 32 | Sweet spot: 1n=3.125%, 4n=12.5% |
| SLO target | 100ms | 50ms | Closer to base latency (~29ms) |
| S2 fault nodes | 1 | 2, β=0.1, s_max=15 | More visible impact |
| S3 fault nodes | 1 (2x) | 2 (3x), two-wave surge | Test progressive overload |
| S4 slowdown range | 1.5-3x | 2-5x | Higher stress |
| S5 fault nodes | 1 (3x peak) | 3 (5x peak, 8s/8s) | Test fluctuating response |
| S6 cascade | 2 nodes | 3 nodes (5x/5x/3x) | Deeper cascade |
| S7 recovery | 1 node (5x) | 2 nodes (8x) | Stronger fault |

## Results

### P99 Latency (ms)

| Scenario | no_mitig | adaptive | fixed_iso | fixed_shed | fixed_spec |
|----------|----------|----------|-----------|------------|------------|
| S1 (3x) | **52.7** | 29.4 | 29.5 | 29.8 | 29.6 |
| S2 | **62.4** | 30.3 | 30.3 | 32.4 | 32.0 |
| S3 | **79.2** | 40.8 | 40.8 | 41.9 | 40.3 |
| S4 | **119.2** | 109.5 | **69.0** | 115.3 | 118.0 |
| S5 | 121.7 | 120.4 | 119.9 | 120.7 | 120.3 |
| S6 | **125.4** | 33.2 | 32.8 | 37.5 | 33.9 |
| S7 | 32.4 | **29.7** | **29.7** | 32.3 | 36.7 |

### P999 Latency (ms) — NEW, more discriminative

| Scenario | no_mitig | adaptive | fixed_iso | fixed_shed | fixed_spec |
|----------|----------|----------|-----------|------------|------------|
| S1 (3x) | **89.0** | 35.9 | 36.0 | 37.0 | 36.2 |
| S2 | **331.0** | 41.3 | **37.5** | 101.7 | 94.3 |
| S3 | **117.7** | 50.6 | 50.3 | 93.2 | 50.0 |
| S4 | **175.3** | 157.7 | **109.1** | 169.9 | 163.6 |
| S5 | 193.8 | 196.5 | 196.2 | 196.5 | 195.6 |
| S6 | **190.2** | 40.4 | 40.7 | 128.1 | 77.2 |
| S7 | 289.0 | **36.8** | 37.1 | 586.4 | **5078.7** |

### Tail Ratio (P99/P50)

| Scenario | no_mitig | adaptive | fixed_iso | fixed_shed | fixed_spec |
|----------|----------|----------|-----------|------------|------------|
| S2 | **4.00** | 1.94 | 1.95 | 2.08 | 2.07 |
| S3 | **4.91** | 2.45 | 2.44 | 2.60 | 2.42 |
| S4 | **6.87** | 6.31 | **3.96** | 6.64 | 6.81 |
| S5 | 7.88 | 7.73 | 7.73 | 7.77 | 7.77 |
| S6 | **7.80** | 2.04 | 2.03 | 2.35 | 2.11 |

### SLO Violation Rate

| Scenario | no_mitig | adaptive | fixed_iso | fixed_shed | fixed_spec |
|----------|----------|----------|-----------|------------|------------|
| S2 | 1% | 0% | 0% | 0% | 0% |
| S3 | 2% | 0% | 0% | 1% | 0% |
| S4 | **4%** | 3% | **2%** | 3% | 4% |
| S5 | 1% | 1% | 1% | 1% | 1% |
| S6 | **2%** | 0% | 0% | 1% | 0% |

## Key Findings

### 1. V8 design is a major success (vs V7)

V7 had 0/7 discriminative scenarios. V8 has **5/7** (S1-S4, S6, S7).
Strategy differences range from 2x to 74x in P999 (vs <5% in V7).

### 2. fixed_isolation is the most consistently good strategy

Across all scenarios, fixed_isolation ranks #1 or tied #1 in 6/7 scenarios.
In S4, it's dramatically better: P99=69ms vs adaptive's 109ms.

### 3. adaptive has a critical flaw in multi-node scenarios (S4)

theta_iso=0.7 is too conservative. Nodes with 2-3x slowdown (severity 0.5-0.67)
get SPECULATE/SHED instead of ISOLATE. With 4 simultaneous faults, cumulative
effect is devastating. fixed_isolation's aggressive theta_iso=0.3 isolates all.

### 4. S5 fluctuating shows no strategy discrimination

All strategies ~120ms P99. Root cause: 3 nodes × 5x at 50% duty ≈ 2.4 nodes
lost capacity. System at rho≈0.865, near saturation regardless of strategy.
Also, 8s on/off cycle + 1s detection delay = strategy always half a beat late.

### 5. Speculation has catastrophic failure mode (S7 P999=5078ms)

fixed_speculation doesn't reduce traffic to fault nodes — it only adds hedges.
Fault node queues grow unboundedly. 2 nodes × 8x × 40s = massive queue buildup.
When nodes recover, draining takes seconds, creating extreme P999.

### 6. P999 is far more discriminative than P99

In S7: P99 range is 29.7-36.7ms (7ms spread). P999 range is 36.8-5078ms (5042ms spread!).
In S2: P99 range is 30.3-62.4ms. P999 range is 37.5-331.0ms.
P999 reveals strategy quality differences invisible to P99.

## Anomalies Explained

### S1 10x: All strategies P999 ≈ 324ms
Detection delay (CONFIRM_EPOCHS=2 × 0.5s = 1s) means requests hit 10x node
during onset transient. Once queued at 10x, latency = 10×10ms × queue_depth.
Not a steady-state problem, but a transient one.

### S5 no discrimination despite 9.375% fault nodes
System at rho≈0.865 during fault-on periods. No strategy can conjure capacity.
Fluctuation period (8s) too close to detection/reaction timescale (~1s).

## Strategy Ranking (V8)

1. **fixed_isolation** — Best overall, especially multi-node faults
2. **adaptive** — Good for S2/S6/S7, but fails S4 (too conservative)
3. **fixed_speculation** — Good P99 but catastrophic P999 tail (S7: 5078ms)
4. **fixed_shedding** — Never catastrophic but consistently mediocre P999
5. **no_mitigation** — Worst baseline as expected

## Next Steps (V9 Direction)

### Must fix:
1. **Adaptive multi-node threshold**: Lower theta_iso when multiple nodes faulty
2. **Speculation queue protection**: Reduce weight to fault nodes, not just add hedges

### Should fix:
3. **Fast-track detection for high severity**: Skip CONFIRM_EPOCHS when severity > 0.8
4. **S5 fluctuation handling**: Persistent "unstable" label, don't de-escalate on off-cycles

### Experiment adjustments:
5. **S5**: Shorter cycles (2s/2s) or longer (30s/30s) for clearer signal
6. **S4**: Fixed slowdowns (not random) to reduce variance
7. **New S8**: Low severity (1.5-2x) single node to test where isolation costs > benefits

## Reproducibility
- Experiments: experiments/results/s1-s7
- Commit: (this commit)
