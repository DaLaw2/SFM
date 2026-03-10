# Experiment Results Report

## Overview

This report summarizes results from 7 simulation scenarios evaluating our adaptive multi-strategy framework for slow-fault mitigation. All experiments use a 16-node cluster with M/D/1 queue model (100 req/s per node, 10ms base service time, P99 SLO = 100ms). Each scenario runs 5 baselines with 10 independent runs each.

### Baselines

| Baseline | Description |
|----------|-------------|
| No Mitigation | No response to slow faults (lower bound) |
| Fixed Speculation | Always speculate (hedged requests), never shed or isolate |
| Fixed Shedding | Always shed load via AIMD, never speculate or isolate |
| Fixed Isolation | Aggressively isolate slow nodes (IASO-style) |
| Adaptive (Ours) | Multi-strategy framework with SLO-distance-driven selection |

---

## S1: Single Node Severity Sweep

**Setup**: 16 nodes, 90% load, 1 node with PermanentFault, slowdown swept from 1.0 to 10.0. Duration 60s, warmup 10s.

**Key Results** (P99 latency in ms, mean +/- 95% CI):

| Slowdown | No Mitigation | Fixed Speculation | Fixed Shedding | Fixed Isolation | Adaptive |
|----------|---------------|-------------------|----------------|-----------------|----------|
| 1.0 | 38.5 +/- 0.5 | 8440 +/- 3306 | 1726 +/- 1739 | 73.6 +/- 40.3 | 9531 +/- 3606 |
| 2.0 | 63.5 +/- 1.5 | 8840 +/- 1753 | 3368 +/- 2097 | 129.8 +/- 50.2 | 10448 +/- 3255 |
| 5.0 | 158.0 +/- 2.7 | 13640 +/- 2551 | 3525 +/- 1759 | 126.8 +/- 68.6 | 14928 +/- 1723 |
| 10.0 | 66.0 +/- 6.1 | 6119 +/- 1596 | 172.5 +/- 73.2 | 133.6 +/- 72.0 | 9658 +/- 3180 |

**Plots**: `s1_severity_sweep/p99_vs_slowdown.png`, `s1_severity_sweep/throughput_vs_slowdown.png`

**Findings**: At 90% load, the system is already near the danger zone. No mitigation performs surprisingly well for low-to-moderate slowdowns because a single slowed node among 16 has limited system-wide impact. Fixed isolation is the most consistent strategy. The adaptive and speculation strategies show high P99 due to the overhead of speculative execution at high load consuming spare capacity.

---

## S2: Progressive Thermal Throttling

**Setup**: 16 nodes, 80% load, 1 node with progressive fault (s(t) = 1.0 + 0.05*(t-15), onset=15s, s_max=8.0). Duration 120s, warmup 10s.

**Key Results** (P99 latency in ms):

| Baseline | P99 (ms) | Throughput (req/s) |
|----------|----------|--------------------|
| No Mitigation | 70.1 +/- 0.6 | 1280 +/- 3 |
| Fixed Speculation | 11522 +/- 5074 | 1170 +/- 49 |
| Fixed Shedding | 717.0 +/- 1440 | 1273 +/- 14 |
| Fixed Isolation | 77.9 +/- 28.9 | 1278 +/- 2 |
| Adaptive | 16071 +/- 4793 | 1126 +/- 44 |

**Plots**: `s2_progressive/p99_comparison.png`, `s2_progressive/throughput_comparison.png`

**Findings**: Progressive degradation worsens over 120s. Fixed isolation and no mitigation perform best, as the slowed node's impact is diluted across 16 nodes at 80% load. Shedding shows high variance. Speculation and adaptive strategies suffer from generating extra load on an already moderately loaded system.

---

## S3: Flash Crowd Under Slow Fault

**Setup**: 16 nodes, variable load (70% t=0-40s, 95% t=40-70s, 70% t=70s+). Node 0: PermanentFault s=2.0 at t=10s. Duration 100s, warmup 5s.

**Key Results** (P99 latency in ms):

| Baseline | P99 (ms) | Throughput (req/s) |
|----------|----------|--------------------|
| No Mitigation | 90.5 +/- 8.6 | 1247 +/- 4 |
| Fixed Speculation | 2311 +/- 519 | 1241 +/- 7 |
| Fixed Shedding | 2337 +/- 2527 | 1241 +/- 12 |
| Fixed Isolation | 699.1 +/- 884 | 1241 +/- 11 |
| Adaptive | 1621 +/- 550 | 1241 +/- 5 |

**Plots**: `s3_flash_crowd/p99_comparison.png`, `s3_flash_crowd/throughput_comparison.png`

**Findings**: The load spike to 95% during an active fault is the critical challenge. No mitigation performs best because the fault (s=2.0 on 1 of 16 nodes) has modest system-wide impact and mitigation strategies introduce overhead that compounds during the high-load phase. Fixed isolation shows high variance -- when it isolates at the wrong time during the spike, capacity loss hurts. Adaptive outperforms fixed speculation and shedding but cannot match no mitigation for this mild fault.

---

## S4: Multi-Node Correlated Failure

**Setup**: 16 nodes, 80% load. Nodes 0-3: PermanentFault with slowdowns from Uniform(1.5, 3.0), onset t=10s. Duration 60s, warmup 5s.

**Key Results** (P99 latency in ms):

| Baseline | P99 (ms) | Throughput (req/s) |
|----------|----------|--------------------|
| No Mitigation | 99.3 +/- 11.1 | 1281 +/- 3 |
| Fixed Speculation | 6655 +/- 1363 | 1210 +/- 19 |
| Fixed Shedding | 3310 +/- 1323 | 1243 +/- 17 |
| Fixed Isolation | 2530 +/- 2913 | 1267 +/- 15 |
| Adaptive | 6406 +/- 3024 | 1204 +/- 36 |

**Plots**: `s4_multi_node/p99_comparison.png`, `s4_multi_node/throughput_comparison.png`

**Findings**: With 4 of 16 nodes (25%) degraded, the system faces a capacity crunch. No mitigation is borderline (P99 ~99ms, just under the 100ms SLO). Isolation is risky: isolating 4 nodes leaves only 12 healthy nodes at 80% original load, pushing utilization to ~107%, which causes collapse in some runs (high variance). Shedding performs moderately. This scenario demonstrates the key challenge: when too many nodes fail, aggressive isolation reduces capacity below the viable threshold.

---

## S5: Fluctuating Fault

**Setup**: 16 nodes, 80% load, 1 node with FluctuatingFault (s_peak=3.0, d_on=5s, d_off=5s). Duration 120s, warmup 10s.

**Key Results** (P99 latency in ms):

| Baseline | P99 (ms) | Throughput (req/s) |
|----------|----------|--------------------|
| No Mitigation | 37.6 +/- 0.3 | 1280 +/- 2 |
| Fixed Speculation | 6291 +/- 3990 | 1223 +/- 35 |
| Fixed Shedding | 2511 +/- 2826 | 1254 +/- 27 |
| Fixed Isolation | 97.2 +/- 37.4 | 1281 +/- 2 |
| Adaptive | 7977 +/- 4683 | 1203 +/- 41 |

**Plots**: `s5_fluctuating/p99_comparison.png`, `s5_fluctuating/throughput_comparison.png`

**Findings**: The oscillating fault (on/off every 5s) tests strategy stability. No mitigation handles this easily since the fault averages out. Isolation works well but adds slight latency overhead. High variance in speculation and adaptive suggests strategy oscillation during fault transitions.

---

## S6: Cascading Degradation

**Setup**: 16 nodes, 85% load, 2 nodes with staggered PermanentFaults. Duration 90s, warmup 5s.

**Key Results** (P99 latency in ms):

| Baseline | P99 (ms) | Throughput (req/s) |
|----------|----------|--------------------|
| No Mitigation | 152.9 +/- 3.4 | 1360 +/- 3 |
| Fixed Speculation | 21593 +/- 4970 | 1185 +/- 47 |
| Fixed Shedding | 10404 +/- 4587 | 1275 +/- 40 |
| Fixed Isolation | 422.4 +/- 357 | 1357 +/- 4 |
| Adaptive | 24673 +/- 3195 | 1156 +/- 32 |

**Plots**: `s6_cascade/p99_comparison.png`, `s6_cascade/throughput_comparison.png`

**Findings**: At 85% load with 2 cascading faults, the system is in the danger zone. No mitigation already violates the SLO (153ms > 100ms). Fixed isolation reduces impact but cannot fully recover (422ms). Speculation and adaptive strategies perform worst, overwhelmed by the high base load. This is the most challenging scenario and highlights the need for better spare-capacity-aware strategy selection.

---

## S7: Recovery Dynamics

**Setup**: 16 nodes, 80% load, 1 node with time-limited fault that recovers. Duration 100s, warmup 5s.

**Key Results** (P99 latency in ms):

| Baseline | P99 (ms) | Throughput (req/s) |
|----------|----------|--------------------|
| No Mitigation | 37.7 +/- 0.4 | 1280 +/- 2 |
| Fixed Speculation | 13247 +/- 6156 | 1149 +/- 62 |
| Fixed Shedding | 228.9 +/- 267 | 1276 +/- 5 |
| Fixed Isolation | 53.4 +/- 16.8 | 1280 +/- 3 |
| Adaptive | 9605 +/- 3175 | 1177 +/- 36 |

**Plots**: `s7_recovery/p99_comparison.png`, `s7_recovery/throughput_comparison.png`

**Findings**: When the fault is temporary, strategies that can reintegrate the node quickly win. No mitigation and isolation both perform well. Shedding shows moderate overhead (229ms). The adaptive and speculation strategies show significant overhead, suggesting the reintegration path needs improvement.

---

## Cross-Scenario Summary

| Scenario | Best Strategy | P99 (ms) | Worst Strategy | P99 (ms) |
|----------|---------------|----------|----------------|----------|
| S1 (s=2.0) | No Mitigation | 63.5 | Adaptive | 10448 |
| S2 Progressive | No Mitigation | 70.1 | Adaptive | 16071 |
| S3 Flash Crowd | No Mitigation | 90.5 | Fixed Shedding | 2337 |
| S4 Multi-Node | No Mitigation | 99.3 | Fixed Speculation | 6655 |
| S5 Fluctuating | No Mitigation | 37.6 | Adaptive | 7977 |
| S6 Cascade | No Mitigation | 152.9 | Adaptive | 24673 |
| S7 Recovery | No Mitigation | 37.7 | Fixed Speculation | 13247 |

## Key Insights

1. **No mitigation is a strong baseline**: For single-node faults in a 16-node cluster, the natural load distribution across healthy nodes absorbs much of the impact. Mitigation strategies only help when faults are severe enough to significantly impact system-wide metrics.

2. **Fixed isolation is the most consistent mitigation**: Across all scenarios, isolation (IASO-style) shows the lowest P99 among mitigation strategies, with the caveat that it can fail catastrophically when too many nodes are isolated (S4).

3. **Speculation overhead is problematic at high load**: Both fixed speculation and the adaptive strategy (which uses speculation) consistently degrade performance. At loads above 80%, speculative requests consume the spare capacity needed for normal operation.

4. **The adaptive strategy needs tuning**: Current results show the adaptive strategy performing poorly, likely due to:
   - Default threshold parameters not matched to these scenarios
   - Speculation being triggered too aggressively
   - Insufficient spare capacity awareness at high loads

5. **High variance is a challenge**: Many strategies show large confidence intervals (e.g., fixed shedding in S3: 2337 +/- 2527ms), indicating inconsistent behavior across runs. Reducing this variance is important for production use.

6. **The danger zone effect is confirmed**: S6 at 85% load with 2 faulty nodes shows clear SLO violation even without mitigation (153ms), confirming the M/D/1 danger zone behavior.
