# V01 Findings: Initial Experiment Results

**Date**: 2026-03-07
**Baseline**: 917aecd

## Context

First full round of experiments (S1-S7) after fixing 10+ bugs in the simulator,
including connecting the previously-dead speculation/hedging system (C1),
composing overlapping fault scenarios (C3), and parallelizing S1/S2 experiments.

## Key Finding: Mitigation Overhead Exceeds Benefit at High Load

At 80-90% system utilization, ALL mitigation strategies (including adaptive)
perform worse than no_mitigation in most scenarios. This is NOT because the
strategies are fundamentally flawed, but because of the interaction between
hedging overhead and M/D/1 queue nonlinearity.

### Evidence

**S1 (90% load, no fault, s=1.0):**
- no_mitigation: P99 = 38.1ms
- adaptive: P99 = 91.8ms
- Mitigation adds ~54ms overhead even with zero faults

**S1 (90% load, s=3.0):**
- no_mitigation: P99 = 98.0ms
- fixed_speculation: P99 = 2000.6ms (catastrophic)
- fixed_isolation: P99 = 115.3ms (best mitigation strategy)

**DR-008 (70% load, s=3.0) -- previous validation:**
- no_mitigation: P99 = 59.5ms
- mitigation ON: P99 = 28.4ms
- **Mitigation improves P99 by 52% at 70% load**

### Where Mitigation DOES Help

| Condition | Result |
|-----------|--------|
| 70% load + moderate fault | 52% P99 improvement (DR-008) |
| 90% load + severe fault (s=5x), isolation | P99 96ms vs 161ms (within SLO) |
| S6 cascade (85%), isolation | SLO violation 60% vs 100% |

### Where Mitigation HURTS

| Condition | Result |
|-----------|--------|
| 80-90% load + no/mild fault + speculation | +54-140ms overhead from hedging |
| 80-90% load + any fault + speculation | Queue explosion, up to 2000ms P99 |
| S3 flash crowd (95% peak) + any strategy | All strategies worse than no_mitigation |

## Root Cause Analysis

Five interacting factors:

### 1. Hedging Doubles Effective Load on Healthy Workers

At 90% utilization (1440 req/s across 16 workers), each worker handles 90 req/s.
Hedging sends copies to healthy workers, pushing them from 90% to 99%+ utilization.
M/D/1 queueing delay: rho=0.90 -> 10x factor, rho=0.99 -> 100x factor.
Even 3% more load from hedges causes 47% latency increase.

### 2. Cancelled Hedges Still Occupy Queue Slots

In worker._handle(), the SimPy Resource is acquired BEFORE checking request.cancelled.
A cancelled hedge request blocks in queue while waiting, increasing queue depth
for real requests behind it.

### 3. False Positive Detection at High Load

At 90% load, natural queueing variance causes some healthy nodes to appear 20%+
slower than median. Detector severity = 1 - (median/node_p99) = 16.7% for a 1.2x
node, which exceeds theta_spec (10%). This triggers SPECULATE on healthy nodes.

### 4. Spare Capacity Miscalculated

Monitor uses config.arrival_rate (static) instead of observed throughput.
Hedge traffic is invisible to the spare capacity calculation, so the system
thinks it has 10% spare when actual utilization is 99%+.

### 5. Power-of-2-Choices Provides Strong Implicit Mitigation

The load balancer's power-of-2-choices naturally avoids slow nodes (longer queue
-> less likely to be selected). For single-node faults in 16-node clusters,
this implicit mitigation is remarkably effective, making explicit intervention
less necessary.

## Experiment Results Summary

### P99 Latency (ms) by Scenario

| Scenario | Load | no_mitig | fixed_spec | fixed_shed | fixed_iso | adaptive |
|----------|------|----------|------------|------------|-----------|----------|
| S2 Progressive | 80% | 70.6 | 227.7 | 77.9 | 74.7 | 79.8 |
| S3 Flash Crowd | 70-95% | 91.7 | 296.0 | 312.4 | 308.0 | 249.7 |
| S4 Multi-Node | 80% | 105.2 | 2047.3 | 320.3 | 368.0 | 328.4 |
| S5 Fluctuating | 80% | 37.4 | 81.4 | 63.2 | 94.8 | 82.0 |
| S6 Cascade | 85% | 153.8 | 204.9 | 184.6 | 164.4 | 192.9 |
| S7 Recovery | 80% | 37.8 | 96.7 | 51.7 | 111.7 | 90.4 |

### SLO Violation Rate by Scenario

| Scenario | no_mitig | fixed_spec | fixed_shed | fixed_iso | adaptive |
|----------|----------|------------|------------|-----------|----------|
| S2 | 0% | 40% | 20% | 10% | 10% |
| S3 | 20% | 100% | 100% | 100% | 100% |
| S4 | 70% | 100% | 100% | 100% | 100% |
| S5 | 0% | 20% | 10% | 30% | 20% |
| S6 | 100% | 100% | 90% | 60% | 100% |
| S7 | 0% | 10% | 0% | 40% | 10% |

## Implications for Research

### Topic Does NOT Need to Change

The research gap (no dynamic multi-strategy selection for slow faults) still holds.
The framework architecture (SPECULATE -> SHED -> ISOLATE state machine + SLO-distance
adaptive thresholds + AIMD recovery) is sound.

### What Needs to Change

The framework is missing **load-awareness as a first-class signal**. Currently,
adaptive thresholds only scale with SLO distance (urgency). They must also scale
with system load/spare capacity.

### Proposed Modifications (Priority Order)

1. **M1: Fix spare_capacity** - Use observed throughput instead of config.arrival_rate
2. **M2: Load-aware theta_spec** - Scale speculation threshold UP when spare is LOW
3. **M3: Hedge rate budget** - Limit hedges/sec to fraction of spare capacity
4. **M4: Cost-benefit gate** - Selector chooses NORMAL when overhead > fault impact
5. **M5: Load-aware detector** - Raise MIN_LATENCY_RATIO at high load
6. **M6: 2D experiment sweep** - load_factor x slowdown grid, primary at 70% load

### Strengthened Research Narrative

"Naive mitigation can be worse than no mitigation due to the interaction between
hedging overhead and M/D/1 queue nonlinearity. Load-aware adaptive selection is
the key to avoiding this 'mitigation trap' while providing benefit when capacity
permits."

This is a STRONGER contribution than "adaptive beats all fixed strategies" because
it reveals a non-obvious phenomenon, explains why, and provides a principled solution.

## Reproducibility

All code and results for this experiment round are archived in:
- Git commit: 917aecd
- Git tag: v1-initial-experiments
- Physical archive: archive/v1_initial_experiments/
