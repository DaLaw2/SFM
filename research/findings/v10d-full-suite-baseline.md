# V10 Findings: Full S1-S7 Suite Baseline

**Date**: 2026-03-08
**Baseline**: c407663

## Purpose

Establish baseline results for all scenarios with current parameters:
- 32 nodes, SLO 50ms, theta_iso=0.5
- S5 fixed with 2 fault nodes (previously undiscriminative with 3)

## Results Summary (P99 ms / P999 ms / SLO Violation %)

### S2 Progressive (2 faults, β=0.1 → s_max=15, 10 runs)
| Baseline | P99 | P999 | SLO Viol% |
|----------|-----|------|-----------|
| adaptive | 30.4 | 37.6 | 0.001% |
| fixed_isolation | 30.6 | 37.7 | 0.0001% |
| fixed_speculation | 32.0 | 84.8 | 0.22% |
| fixed_shedding | 32.6 | 104.5 | 0.34% |
| no_mitigation | 61.8 | 331.6 | 1.10% |

### S3 Flash Crowd (2 faults 3x, two-wave surge, 10 runs)
| Baseline | P99 | P999 | SLO Viol% |
|----------|-----|------|-----------|
| fixed_isolation | 40.0 | 49.4 | 0.077% |
| adaptive | 40.2 | 50.3 | 0.12% |
| fixed_speculation | 40.6 | 53.8 | 0.13% |
| fixed_shedding | 42.2 | 91.9 | 0.63% |
| no_mitigation | 79.5 | 118.0 | 2.05% |

### S4 Multi-Node (4 faults, random 2-5x, 20 runs)
| Baseline | P99 | P999 | SLO Viol% |
|----------|-----|------|-----------|
| **adaptive** | **97.0** | **139.4** | **2.38%** |
| fixed_speculation | 108.6 | 160.9 | 3.40% |
| fixed_isolation | 112.6 | 158.5 | 3.19% |
| fixed_shedding | 117.0 | 167.5 | 3.44% |
| no_mitigation | 125.2 | 177.5 | 3.65% |

### S5 Fluctuating (2 faults, 5x 8s/8s, 20 runs)
| Baseline | P99 | P999 | SLO Viol% |
|----------|-----|------|-----------|
| fixed_isolation | 30.7 | 38.0 | 0.016% |
| adaptive | 31.0 | 43.4 | 0.038% |
| no_mitigation | 35.6 | 173.7 | 0.80% |
| fixed_shedding | 35.9 | 127.5 | 0.48% |
| fixed_speculation | 38.3 | 140.2 | 0.62% |

### S6 Cascade (3 nodes, 5x/5x/3x staggered, 10 runs)
| Baseline | P99 | P999 | SLO Viol% |
|----------|-----|------|-----------|
| fixed_isolation | 32.8 | 40.5 | 0.049% |
| adaptive | 33.1 | 39.4 | 0.041% |
| fixed_speculation | 34.2 | 96.8 | 0.28% |
| fixed_shedding | 43.8 | 134.4 | 0.79% |
| no_mitigation | 125.4 | 190.1 | 2.03% |

### S7 Recovery (2 faults, 8x, 10 runs)
| Baseline | P99 | P999 | SLO Viol% |
|----------|-----|------|-----------|
| adaptive | 29.7 | 37.0 | 0.012% |
| fixed_isolation | 29.7 | 37.0 | 0.012% |
| fixed_shedding | 31.2 | 125.1 | 0.18% |
| no_mitigation | 32.1 | 286.3 | 0.41% |
| fixed_speculation | 38.2 | **5784** | 0.67% |

## Cross-Scenario Strategy Rankings

### P99 Wins (1st or 2nd place)
| Strategy | 1st | 2nd | Worst |
|----------|-----|-----|-------|
| adaptive | 3 (S2,S4,S7) | 3 (S3,S5,S6) | Always top 2 |
| fixed_isolation | 3 (S3,S5,S6) | 3 (S2,S4,S7) | 3rd (S4: 112.6ms) |
| fixed_speculation | 0 | 0 | 5th (S5,S7) |
| fixed_shedding | 0 | 0 | 4th-5th |
| no_mitigation | 0 | 0 | Always last |

### Key Findings

1. **Adaptive is the best overall strategy**: Never worse than 2nd, wins clearly in S4
2. **S4 is the critical weakness**: Even adaptive's 97ms P99 is ~2x SLO target
3. **Adaptive wins S4 by 14% over fixed_isolation**: Multi-node variable severity
   favors adaptive calibration per-node (97 vs 113ms)
4. **S5 now discriminative**: 2-node fix successful (30.7-38.3ms spread vs 119-121ms)
5. **fixed_speculation catastrophic in S7**: P999=5784ms speculation storm during recovery
6. **S3 dominated by load surge**: All strategies cluster at 40-42ms, fault is secondary

## Expert Consensus: Next Research Direction

### Primary: Improve S4 Multi-Node Response
- S4 is the only scenario where ALL strategies fail SLO badly (2.38-3.65% violation)
- Target: P99 below 70ms, SLO violation below 1.5%
- Approaches: parallel fault detection, correlated failure assumption, capacity-aware
  escalation when fault count >= threshold

### Secondary: Speculation Safety Bound
- Cap speculative traffic at N% of cluster throughput (5-8%)
- Prevents S7-style speculation storm without disabling speculation entirely
- The adaptive controller should inherit this safety bound

### Do NOT change:
- S2/S3/S5/S6 gap between adaptive and isolation is tiny (0.2-1.5ms), not worth risking regression
- Fixed strategies are baselines, not deployment candidates
