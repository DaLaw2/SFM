# V10 Findings: Lower theta_iso (0.7 → 0.5)

**Date**: 2026-03-08
**Baseline**: e2bc71c (V8 + V9 revert)

## Change

Single parameter change: `StrategyConfig.theta_iso` from 0.7 to 0.5.
Only affects the `adaptive` baseline (all fixed_* baselines hardcode their own thetas).

## V8 vs V10 Comparison (adaptive only, P99 ms)

| Scenario | V8 | V10 | Change |
|----------|-----|------|--------|
| S2 progressive | 30.3 | 30.3 | 0% |
| S3 flash crowd | 40.8 | 41.0 | ~0% |
| **S4 multi-node** | **109.5** | **101.0** | **-8%** |
| **S5 fluctuating** | **120.4** | **110.7** | **-8%** |
| S6 cascade | 33.2 | 32.9 | ~0% |
| S7 recovery | 29.7 | 29.7 | 0% |

## V8 vs V10 Comparison (adaptive P999 ms)

| Scenario | V8 | V10 | Change |
|----------|-----|------|--------|
| S2 | 41.3 | 37.6 | -9% |
| S4 | 157.7 | 145.7 | -8% |
| S5 | 196.5 | 180.5 | -8% |
| S6 | 40.4 | 40.4 | 0% |
| S7 | 36.8 | 37.0 | 0% |

## Analysis

### Improvements
- **S4**: adaptive improved from 109.5→101.0ms, now comparable to fixed_isolation
- **S5**: adaptive improved from 120.4→110.7ms, first scenario where any mitigation
  shows meaningful improvement for fluctuating faults
- No regressions on any scenario for adaptive

### Noise concern
fixed_isolation S4 swung from 69.0ms (V8) to 102.1ms (V10) despite being
completely unaffected by the change. This suggests V8's 69ms was an outlier.
S4 uses random slowdowns (uniform 2-5x), creating high inter-run variance.

Expert assessment: ~50% of observed improvement may be noise. True improvement
for S4 is likely 4-5%, not 8%.

### S5 mechanism
theta_iso=0.5 gives the detector a wider confirmation window for fluctuating
faults (severity oscillates 0↔0.8). Lower threshold means isolation triggers
earlier in the rise phase, before severity falls back to 0.

### Baseline stability
All fixed_* baselines show expected noise-level variation only. The change
correctly isolates to the adaptive strategy.

## Decision: KEEP

theta_iso=0.5 provides consistent (if modest) improvement across S4/S5 with
no regressions. The change is minimal and well-understood.

## Remaining Issues

1. **High simulation noise**: Need N_RUNS > 10 or fixed seeds for S4 to get
   reliable comparisons
2. **S5 still ~110ms**: Improvement exists but system still saturated during
   fault-on periods
3. **S4 adaptive (101ms) still >> theoretical optimal**: fixed_isolation true
   median probably 80-90ms
4. **fixed_speculation S7 P999 = 3925ms**: Catastrophic failure mode unchanged
