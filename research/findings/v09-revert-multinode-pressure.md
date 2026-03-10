# V09 Findings: Multi-Node Pressure + SPECULATE Weight

**Date**: 2026-03-08
**Baseline**: 8b79971 (V8)
**Status**: REVERTED — changes did not improve results

## V9 Changes (Reverted)

1. **Multi-node pressure**: When n_faulty >= 2 (severity > t_shed), lower t_iso
   by 10% per node, floor at t_shed
2. **SPECULATE weight reduction**: weight = max(0.3, 1.0 - 0.5*sev) for SPECULATE nodes
3. **Capacity guard extended to SPECULATE nodes**

## Results: V8 vs V9

### S4 Multi-Node (Target: improve adaptive)
| Baseline | V8 P99 | V9 P99 | V8 P999 | V9 P999 |
|----------|--------|--------|---------|---------|
| adaptive | 109.5 | 107.1 (-2%) | 157.7 | 153.9 |
| fixed_isolation | **69.0** | **103.7 (+50%)** | 109.1 | 146.2 |

### S6 Cascade (Unexpected regressions)
| Baseline | V8 P99 | V9 P99 |
|----------|--------|--------|
| fixed_shedding | 37.5 | 45.8 (+22%) |
| fixed_speculation | 33.9 | 43.0 (+27%) |

### S7 Recovery
| Baseline | V8 P99 | V9 P99 | V8 P999 | V9 P999 |
|----------|--------|--------|---------|---------|
| fixed_speculation | 36.7 | 47.0 (+28%) | 5078.7 | 5438.4 |

## Why V9 Failed

### 1. Broke fixed_speculation baseline semantics
V9's SPECULATE weight reduction (change #2) affected ALL baselines that use
SPECULATE, including fixed_speculation (theta_spec=0.1). This added unintended
SHED-like behavior to a baseline that was designed to "only speculate, never shed."

### 2. Multi-node pressure insufficient
adaptive S4 only improved 2% (within noise). The real bottleneck is capacity:
4/32 nodes faulty at 80% load → remaining rho = 0.8 * 32/28 = 0.914. At this
utilization, M/D/1 model predicts P99 >> 100ms regardless of strategy thresholds.
The G2 capacity guard (rho < 0.9) prevents full isolation, downgrading to SHED.

### 3. fixed_isolation S4 regression likely noise
fixed_isolation's behavior shouldn't be affected by V9 changes (theta_spec=999,
theta_shed=999 prevents all V9 code paths). The 69→103.7ms swing is likely
seed-dependent simulation variance. S4 uses random slowdowns (uniform 2-5x),
so different seeds produce different fault severities.

## Lessons Learned

1. **Never modify weight/strategy behavior for all strategies when only adaptive needs fixing**
   - SPECULATE weight reduction should have been gated by `enable_mitigation` or strategy config
2. **S4's problem is capacity, not thresholds**
   - At rho=0.914, no threshold adjustment helps
   - Need partial isolation or admission control
3. **Need multi-seed validation before declaring improvements**
   - S4's random slowdowns cause high variance between runs

## Next Steps (from expert consensus)

### Don't try again (exhausted approaches):
- Threshold adjustment for multi-node scenarios (doesn't address capacity bottleneck)
- SPECULATE weight modification (breaks baseline semantics)

### Worth trying:
1. **Partial isolation**: Instead of weight=0 (full isolation), use weight=0.05
   to keep minimal flow to fault nodes, preventing rho explosion on healthy nodes
2. **Lower theta_iso directly**: Change adaptive's theta_iso from 0.7 to 0.4-0.5,
   simpler than complex pressure mechanisms
3. **S5 detection improvement**: Change detector for fluctuating faults
   (persistent "unstable" label, don't de-escalate during off-cycles)
