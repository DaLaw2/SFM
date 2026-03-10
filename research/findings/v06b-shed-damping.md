# V06 Findings: SHED Weight Damping + Capacity Guard

**Date**: 2026-03-08
**Baseline**: 6dee17c (V6)

## Context

V6-final adds two strategy-layer changes to V6's departure interval detection,
based on expert consensus that detection is optimized and S3 is a strategy problem.

### Change 1: SHED Weight Damping (`selector.py`)
- `spare_factor = min(1.0, max(0.0, (spare - 0.08) / 0.15))`
- SHED weight blended: `raw_w * spare_factor + 1.0 * (1 - spare_factor)`
- At spare < 0.08 (rho > 0.92): weight → 1.0, SHED has no traffic effect
- At spare > 0.23: spare_factor = 1.0, normal SHED behavior

### Change 2: SHED Capacity Guard (`selector.py`)
- After computing SHED weights, estimate healthy node rho
- If rho_healthy > 0.88, proportionally scale back all SHED weights
- Extends G2 isolation budget pattern to SHED

## Key Result: Minimal Improvement

| Scenario | no_mitig | V6 | V6-final | Change vs V6 |
|----------|----------|-----|----------|---------------|
| S2 | 70ms | 33.8 | 33.5 | ~same |
| S3 | 80ms | 209 | 179 | -30ms but still 2x worse than no_mitig |
| S4 | 106ms | 122 | 123 | no improvement |
| S5 | 38ms | 33.6 | 33.5 | ~same |
| S6 | 152ms | 80.4 | 87 | slightly worse (damping reduced SHED force) |
| S7 | 38ms | 32.2 | 32.1 | ~same |

## Why SHED Damping Underperformed

### S3: EMA Lag Defeats spare_factor
The spare_factor uses EMA-smoothed spare_capacity (α=0.3). When load jumps
70%→95%, EMA takes ~2 seconds to converge:
- t=0.0: spare_ema ≈ 0.25 → spare_factor = 1.0 (full SHED)
- t=0.5: spare_ema ≈ 0.18 → spare_factor = 0.67
- t=1.0: spare_ema ≈ 0.13 → spare_factor = 0.33
- t=1.5: spare_ema ≈ 0.09 → spare_factor = 0.07
- t=2.0: spare_ema ≈ 0.06 → spare_factor = 0.0

SHED is active with significant force for ~2 seconds at 95% load. At rho=0.95,
even 1-2 seconds of SHED causes severe queue buildup that pollutes P99.

Untried fixes: raw spare (no EMA) for spare_factor, asymmetric EMA (α_down=0.7),
or spare change-rate trigger.

### S4: Parameters Too Lenient
At 80% load, spare ≈ 0.20, spare_factor = (0.20-0.08)/0.15 = 0.80. Barely
any damping. Capacity guard triggers at rho_healthy > 0.88, but with 4 nodes
at weight≈0.6, rho_healthy ≈ 0.889 — just barely over threshold, minimal
adjustment.

### S6: Over-Damping at 85% Load
At 85% load, spare ≈ 0.15, spare_factor ≈ 0.47. SHED force is halved,
reducing effectiveness against cascade faults. V6 was 80ms, V6-final is 87ms.

## Scenario Validity Discussion

### Critical Re-evaluation of Experimental Scenarios

Post-V6 discussion identified fundamental issues with scenario design:

1. **Cluster size (16 nodes) is unrealistic.** Production systems have hundreds
   to thousands of nodes. 1 faulty node = 6.25% of capacity in 16-node cluster
   vs 0.1% in 1000-node cluster. This amplifies all effects.

2. **S3's 95% spike exceeds design capacity.** Industry standard: 60-70%
   target utilization with 30-40% headroom. 95% is capacity planning failure,
   not a mitigation scenario. With 1 faulty node at 95% load, system is at
   rho=0.98 — near saturation regardless of mitigation.

3. **S1's 90% base load is too high.** Same reasoning — 80% is more realistic.

4. **M/D/1 model is simplified.** Real systems have heavy-tailed service times,
   bursty arrivals, dependency chains. P2C effectiveness may differ.

### Proposed Scenario Adjustments for Next Phase

| Parameter | Current | Proposed | Rationale |
|-----------|---------|----------|-----------|
| Cluster size | 16 | 64 | Realistic scale |
| S1 base load | 90% | 80% | Within design range |
| S3 spike | 70→95→70% | 70→85→70% | Reasonable surge |
| S4 fault count | 4/16 (25%) | 4/64 (6.25%) | Realistic proportion |
| S6 fault count | 2/16 | 2/64 | Keep absolute count |

## Expert Consensus: Detector Is Done

All three expert panels (queueing theory, control systems, distributed systems)
unanimously agreed:
- Departure interval detector is theoretically optimal (load-invariant)
- No further detector modifications needed
- Remaining work is strategy-layer and scenario design

## Reproducibility

- Git commit: (pending)
- V6 baseline: commit 6dee17c
- Results: experiments/results/s1_severity_sweep/ through s7_recovery/
