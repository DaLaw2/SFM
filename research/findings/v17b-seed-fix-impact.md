# V17b Findings: Seed Fix Reveals Confounded Adaptive Advantage

**Date**: 2026-03-08

## The Problem

Previous seed generation (`abs(hash(bl.name)) % 100000 + run_id`) gave each baseline a different random stream. This confounded comparisons — performance differences could arise from different arrival patterns rather than strategy differences.

After fixing to `base_seed + run_id` (all baselines share the same seed per run), the high-load results changed dramatically.

## Data Comparison

### Minimax regret (ms) across S3/S4/S6 fault scenarios

**Old (hash-based seeds):**

| Strategy | L=0.80 | L=0.85 | L=0.88 | L=0.90 |
|---|---|---|---|---|
| adaptive | 0.2 | 73.1 | **26.7** | **39.6** |
| fixed_iso | 1.2 | 73.7 | 35.4 | 40.4 |
| lit_blacklist | **0.0** | **0.6** | 151.0 | 1197.1 |
| no_mitig | 89.0 | 88.2 | 88.1 | 63.9 |

**New (fixed seeds):**

| Strategy | L=0.80 | L=0.85 | L=0.88 | L=0.90 |
|---|---|---|---|---|
| adaptive | 7.1 | 90.0 | 26.6 | **34.8** |
| fixed_iso | 1.4 | 86.3 | **18.8** | 34.9 |
| lit_blacklist | **0.0** | **0.2** | 189.7 | 1146.5 |
| no_mitig | 86.9 | 88.7 | 88.8 | 51.3 |

### Key changes
1. **L=0.88:** fixed_iso (18.8ms) now BEATS adaptive (26.6ms). Previously adaptive appeared 25% better.
2. **L=0.90:** Tied (34.8 vs 34.9). Previously adaptive appeared slightly better.
3. **L=0.85:** Both much worse than before (~86-90ms vs ~73ms). The S4 scenario is devastating for both.

## Detailed P99 breakdown (ms) at L=0.88

| Baseline | S3 (2-node, 3x) | S4 (4-node, mixed) | S6 (cascade) |
|---|---|---|---|
| adaptive | 56.2 | 170.2 | 74.8 |
| fixed_iso | 49.2 | 175.5 | 67.0 |
| lit_blacklist | 40.1 | 351.9 | 48.2 |
| no_mitig | 87.9 | 162.2 | 137.0 |

At L=0.88, fixed_iso is actually better than adaptive on S3 (49.2 vs 56.2) and S6 (67.0 vs 74.8). The adaptive framework's multi-strategy overhead provides no benefit when a single strategy (isolation) suffices.

## Root Cause Analysis

The previous "25-33% improvement" was an artifact of unpaired comparison:
- Different baselines had different arrival sequences
- Random variation in arrival patterns could favor or disfavor any strategy
- With paired seeds, the systematic advantage disappears

## Impact on Paper

The following claims are no longer supported:
1. Abstract: "outperforming static isolation by 25--33% in minimax regret at high load"
2. Evaluation: "At L≥0.88, adaptive achieves the lowest minimax regret (26.7ms vs fixed_isolation's 35.4ms, a 25% improvement)"
3. Conclusion: references to adaptive's high-load advantage

## What Still Holds

1. **Operating envelope** ($f_{max} = 1 - L/U$): Validated, independent of seed
2. **Severity non-monotonicity** ($s^*$ formula): Validated, independent of seed
3. **Reactive vs proactive gap**: Massive and consistent across all seeds
4. **lit_blacklist catastrophic failure at high load**: Consistent (189.7ms at L=0.88, 1146.5ms at L=0.90)
5. **Three-tier performance structure**: Still clear

## Open Question

What is adaptive's true differentiation? Possible avenues:
- Scenarios where isolation is infeasible (too many faults, capacity too tight)
- Mixed-severity scenarios where different nodes need different strategies
- Transient/fluctuating faults where strategy switching matters
- Graceful degradation vs cliff-edge behavior
