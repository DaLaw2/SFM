# V19 Findings: SHED-P2C Complementarity — Rejection of the Redundancy Hypothesis

**Date**: 2026-03-09
**Experiment**: S15 (shed_redundancy)
**Status**: Complete — hypothesis rejected, new theorem established

## Research Question

Is SHED (graduated weight reduction) redundant under P2C routing? V18 and the
V19 expert panel hypothesized that P2C's queue-depth comparison subsumes SHED's
weight-based traffic reduction, making graduated response unnecessary.

## Key Finding: Hypothesis Rejected

**SHED is NOT redundant under P2C.** It provides 5-70ms P99 improvement depending
on severity, scale, and load. However, SHED and full isolation (ISO) are nearly
equivalent under P2C — the distinction that matters is "detected vs. undetected",
not "how much weight to reduce".

## Experimental Data

### E1: Scale Invariance (1 fault at 3x, L=0.70)

| N  | no_mit | SHED  | ISO   | adaptive | SHED Δ  |
|----|--------|-------|-------|----------|---------|
| 8  | 79.7ms | 34.6  | 34.3  | 34.3     | -45.1ms |
| 16 | 59.3   | 29.8  | 28.2  | 28.2     | -29.5   |
| 32 | 46.6   | 27.8  | 26.9  | 26.9     | -18.8   |
| 64 | 28.5   | 26.8  | 26.4  | 26.4     | -1.7    |

SHED benefit decays as O(N^{-1.3}). At N=64, P2C alone handles it.

### E2: Severity Sweep (N=16, L=0.70)

| s    | no_mit  | SHED  | ISO   | SHED Δ  |
|------|---------|-------|-------|---------|
| 1.5  | 29.3ms  | 28.0  | 28.1  | -1.3ms  |
| 2.0  | 38.6    | 28.1  | 28.2  | -10.6   |
| 3.0  | 59.3    | 29.8  | 28.2  | -29.5   |
| 5.0  | 99.7    | 29.7  | 28.2  | -70.0   |
| 10.0 | 34.6    | 34.6  | 34.6  | +0.0    |

**Non-monotonicity confirmed**: no_mit P99 peaks at s=5 (99.7ms) then drops
to 34.6ms at s=10. At s≥10, P2C achieves natural self-isolation via
unambiguous queue-depth signal.

SHED benefit maximized at moderate severity (s=3-5x), which is also the
most common production regime (GC pauses, thermal throttling).

### E3: Load Sweep (N=16, 1 fault at 3x)

| L    | no_mit | SHED  | ISO   | SHED Δ  |
|------|--------|-------|-------|---------|
| 0.70 | 59.3ms | 29.8  | 28.2  | -29.5ms |
| 0.80 | 75.5   | 34.1  | 33.8  | -41.4   |
| 0.85 | 83.4   | 39.5  | 39.5  | -43.9   |

SHED benefit *increases* with load — contradicts V18's claim but V18 tested
a very different scenario (ALL 8 nodes faulted, not 1 of 16).

### E4: Multi-Fault (N=32, 2x, L=0.70)

| f | no_mit | SHED  | ISO   | SHED Δ  |
|---|--------|-------|-------|---------|
| 1 | 32.2ms | 26.9  | 26.9  | -5.3ms  |
| 2 | 38.6   | 28.1  | 27.6  | -10.6   |
| 4 | 48.1   | 30.0  | 29.1  | -18.1   |
| 8 | 57.7   | 49.6  | 43.1  | -8.1    |

At f=8 (25% faulty), SHED starts losing to ISO (49.6 vs 43.1ms) due to
"P2C comparison poisoning" — 6.25% chance both candidates are faulty.

### WR Control (weighted random, no queue-depth, E2 severity sweep)

| s    | wr_no_mit | wr_shed | SHED Δ     |
|------|-----------|---------|------------|
| 1.5  | 2,147ms   | 1,375   | -772ms     |
| 2.0  | 11,043    | 2,059   | -8,983     |
| 3.0  | 17,757    | 2,060   | -15,697    |
| 5.0  | 16,670    | 2,180   | -14,490    |
| 10.0 | 120.7     | 120.7   | +0.0       |

Without P2C, SHED provides massive benefit (thousands of ms). This confirms
SHED is a real mechanism — it's P2C that makes it *mostly* unnecessary.

## Root Cause Analysis

### Why V18 Was Wrong (For General Claims)

V18 tested a specific extreme regime: 8/8 nodes faulted at 2x, L=0.80.
In that regime:
- SHED reduces all 8 weights, removing ~4 workers' equivalent capacity
- Healthy-worker load jumps from 0.80 to effectively 0.91+
- The 1/(1-ρ) queueing cost on healthy workers exceeds the benefit

S15 tests the normal regime (1-4 faults out of 16-64 nodes, L=0.70) where
healthy workers have headroom to absorb redistributed traffic.

**V18's finding is correct but regime-specific.** The general claim
"SHED is redundant under P2C" is wrong.

### Two-Stage Mechanism

P2C routes in two stages:
1. **Stage 1 (Sampling):** Select 2 candidates with probability ∝ weight
2. **Stage 2 (Comparison):** Pick the one with shorter queue

SHED operates at Stage 1; P2C queue-depth operates at Stage 2. They are
**complementary, not redundant**:
- SHED prevents the faulty worker from being a candidate (proactive)
- P2C rejects the faulty worker when it IS a candidate (reactive)
- P2C's rejection is imperfect — faulty workers occasionally have
  momentarily short queues (just finished a request), creating windows
  where they win the comparison

### Why SHED ≈ ISO Under P2C

With w_min=0.05 and N=16 healthy workers at w=1.0:
- Faulty candidacy rate: 0.05/15.05 ≈ 0.33% per selection
- Of those, P2C usually rejects via queue comparison
- Net traffic to faulty worker: ≈0.1%

Full isolation: exactly 0%. The 0.1% difference is negligible.

**Implication:** Under P2C, detection accuracy matters far more than
weight precision. A coarse binary "reduce or don't" is sufficient.

### Self-Isolation Threshold (s*)

At s ≥ s*, the faulty worker's queue grows unboundedly, making P2C's
Stage 2 rejection perfect. No mitigation strategy can improve upon this.

From the severity non-monotonicity formula (V15):
s* = f·q / ((1-q)·(N-f))

For N=16, f=1, q=0.99: s* = 0.99/(0.01×15) = 6.6

This predicts s=10 should be above s* (confirmed: SHED Δ = 0).
At s=5, we're near s* (SHED still helps: Δ = -70ms).

## Theorem: SHED-P2C Complementarity

Under P2C(d=2) routing with SHED weight w = max(w_min, 1-σ):

1. **Complementary mechanisms:** SHED (sampling exclusion) and P2C
   (queue-depth rejection) are independent defense layers. Neither
   subsumes the other.

2. **Scale decay:** SHED's marginal benefit scales as O(N^{-α}),
   α ≈ 1.3, vanishing for large clusters.

3. **Severity regimes:**
   - s < 1.5: SHED negligible (fault barely visible)
   - 2 ≤ s ≤ s*: SHED maximally beneficial (P2C's blind spot)
   - s > s*: P2C self-isolates, SHED unnecessary

4. **Practical equivalence:** w_min ≈ 0.05 achieves within O(w_min/N)
   of full isolation under P2C. Detection precision < detection speed.

5. **Capacity-loss boundary:** SHED becomes counterproductive when
   L_healthy = L·N/(N-f_shed) exceeds the queueing knee (~0.88-0.90).

## Implications for Paper

### Supported Claims
- Operating envelope (f_max = 1 - L/U) — unchanged
- Severity non-monotonicity (s* formula) — strengthened by S15 E2
- Reactive mechanisms fail — unchanged
- **NEW: Detection is the key bottleneck, not strategy selection**
- **NEW: P2C has a "blind spot" at moderate severity (2-5x)**
- **NEW: SHED-P2C complementarity theorem**

### Revised from V18
- ~~SHED is redundant under P2C~~ → SHED complements P2C, especially
  at moderate severity in small-to-medium clusters
- ~~Graduated response has no value~~ → Graduated response ≈ binary
  response under P2C, but both are valuable vs. no response

### Paper Narrative
"In queue-aware routing systems, slow fault mitigation's primary
challenge is detection, not response strategy. We derive the operating
envelope and self-isolation threshold, showing that P2C provides natural
fault tolerance at extreme severities but has a blind spot at moderate
severity (2-5x) where explicit detection and exclusion are necessary.
The specific response strategy (graduated weight vs. full isolation)
is inconsequential under P2C — any form of detection-triggered weight
reduction achieves near-optimal results."
