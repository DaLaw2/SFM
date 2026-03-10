# V17 Findings: M/G/1 Generalization & LOR Baseline Validation

**Date**: 2026-03-08

## Context

Three improvements applied simultaneously:
1. **Theory:** Replaced empirical U=0.92 with closed-form U = 1 - t_base/(2·SLO - t_base) = 8/9 ≈ 0.889. Generalized to M/G/1 via Pollaczek-Khinchine: U(C_s) = α/(α + 1 + C_s²).
2. **Simulator:** Added M/G/1 service times (Gamma distribution with configurable CV) and LOR (Least-Outstanding-Requests) load balancing.
3. **Methodology:** Fixed seed generation in runner.py — all baselines now share the same seed per run_id, enabling paired comparisons.

## Part A: M/G/1 Utilization Ceiling Validation

### Theory predictions (mean-latency based)

| C_s² | Distribution | U_theory | f_max at L=0.80 | Max faults (N=32) |
|------|-------------|----------|-----------------|-------------------|
| 0.00 | M/D/1       | 0.889    | 10.0%           | 3.2               |
| 0.25 | M/G/1 mild  | 0.865    | 7.5%            | 2.4               |
| 1.00 | M/M/1       | 0.800    | 0.0%            | 0.0               |

### Empirical results (P99-based SLO crossing)

| C_s² | U_theory (mean) | U_empirical (P99) | Gap      |
|------|-----------------|-------------------|----------|
| 0.00 | 0.889           | > 0.90            | Theory conservative |
| 0.25 | 0.865           | 0.90              | Theory conservative |
| 1.00 | 0.800           | 0.70              | Theory optimistic!  |

### Analysis: Mean vs P99 Discrepancy

The theory derives U from **mean latency** (T(U) ≤ SLO), but the SLO is measured at **P99**.

- **M/D/1 (C_s²=0):** Deterministic service ⟹ low variance in response time ⟹ P99 ≈ mean. Theory is slightly conservative because the P99 has more headroom than the mean.
- **M/G/1 mild (C_s²=0.25):** Moderate variance ⟹ P99 is somewhat above mean, but the gap is manageable. Theory still conservative.
- **M/M/1 (C_s²=1.0):** Exponential service ⟹ P99 ≫ mean. The system's P99 crosses the SLO at L=0.70, well below the mean-based prediction of L=0.80. **The mean-based theory is dangerously optimistic here.**

**Implication:** The closed-form U formula is reliable for low-variance service times (C_s² ≤ 0.25) but requires a P99-specific correction for high-variance distributions. A conservative rule of thumb: for M/M/1, use U ≈ 0.70 rather than the mean-based 0.80.

## Part B: LOR vs P2C Comparison

### P99 Latency (ms), L=0.80, N=32

| Fault           | Baseline        | P2C    | LOR    | Diff    |
|----------------|-----------------|--------|--------|---------|
| S2_progressive | no_mitigation   | 129.7  | 84.3   | **-45.4** |
| S2_progressive | fixed_isolation | 30.8   | 20.7   | -10.2   |
| S2_progressive | adaptive        | 30.8   | 19.9   | -11.0   |
| S4_multi_node  | no_mitigation   | 95.9   | 59.2   | **-36.8** |
| S4_multi_node  | fixed_isolation | 37.8   | 104.4  | **+66.7** |
| S4_multi_node  | adaptive        | 37.7   | 51.2   | +13.5   |
| S6_cascade     | no_mitigation   | 126.9  | 83.3   | **-43.6** |
| S6_cascade     | fixed_isolation | 32.8   | 20.3   | -12.6   |
| S6_cascade     | adaptive        | 32.8   | 19.9   | -12.9   |

### Key Findings

1. **LOR dominates P2C without mitigation:** LOR's full-information routing naturally avoids slow nodes (deeper queues), reducing P99 by 30-45ms. This is expected — LOR uses N choices vs P2C's 2 choices.

2. **LOR + isolation catastrophically fails in S4 (multi-node):** When 4 nodes are isolated, LOR deterministically routes to the shortest queue among the remaining 28 nodes. This creates **synchronization effects** — all requests pile onto the same "shortest" node simultaneously, creating bursty arrivals that spike queueing delay. P99 jumps from 37.8ms (P2C) to 104.4ms (LOR). P2C's randomness acts as natural jitter that prevents this synchronization.

3. **Adaptive partially mitigates the LOR problem:** adaptive under LOR gives 51.2ms (vs 104.4 for fixed_isolation), because load shedding preserves partial capacity from faulty nodes, reducing the load concentration on healthy nodes. But it still exceeds the 50ms SLO.

4. **P2C's randomness is a feature, not a bug:** The "power of two choices" provides near-optimal load balancing while maintaining enough randomness to prevent herd behavior. LOR's deterministic shortest-queue selection, while optimal in theory, creates correlated routing decisions that harm tail latency under capacity-constrained scenarios.

## S1-S7 Re-run Results (Seed Fix Validation)

All S1-S7 experiments re-run with fixed seeds. Qualitative conclusions unchanged:

| Scenario | adaptive | fixed_iso | fixed_shed | fixed_spec | no_mitig |
|----------|----------|-----------|------------|------------|----------|
| S1 (5x)  | 29.4     | 29.4      | 29.7       | 29.5       | 34.3     |
| S2       | 30.5     | 30.5      | 32.5       | 32.1       | 62.1     |
| S3       | 39.9     | 39.9      | 41.7       | 39.8       | 79.1     |
| S4       | 37.6     | 37.6      | 59.6       | 46.9       | 119.5    |
| S5       | 30.8     | 30.8      | 31.4       | 31.9       | 35.7     |
| S6       | 33.2     | 33.2      | 36.4       | 33.5       | 125.3    |
| S7       | 29.8     | 29.9      | 29.9       | 30.0       | 32.3     |

Key observations:
- adaptive and fixed_isolation remain tied at L=0.80 (as expected — differentiation appears at L≥0.88)
- Reactive strategies (not shown, from S11) remain ineffective
- Seed fix did not change any qualitative conclusions

## Open Questions

1. **P99-corrected U formula:** Can we derive a closed-form U based on P99 rather than mean? For M/D/1, the P99 of sojourn time involves the Takács formula, which may not have a clean closed form.
2. **LOR paper positioning:** Should LOR appear as a baseline in the paper, or just as a discussion point? The S4 failure mode is interesting but may distract from the main P2C story.
3. **High-load LOR:** How does LOR perform at L=0.88 with mitigation? The synchronization effect may be even worse.
4. **M/G/1 in the paper:** The current M/G/1 table uses mean-based U. Should we add an empirical column showing the P99 discrepancy, or derive a corrected formula?
