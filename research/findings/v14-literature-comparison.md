# V14 Findings: Literature Baseline Comparison (S11)

**Date**: 2026-03-08
**Baseline**: e333b5e (V13)
**Experiment**: S11 — 8 baselines across S2-S7

## New Literature Baselines

1. **lit_hedged**: Unconditional hedged requests (Dean & Barroso 2013), delay=3×t_base, 10% budget
2. **lit_blacklist**: Outlier blacklisting (Cassandra dynamic snitch style), k=2.0, cooldown=3 epochs
3. **lit_retry**: Timeout retry, deadline=70% SLO, 10% budget

## P99 Latency (ms) — All 8 Baselines

| Scenario | adaptive | lit_blacklist | fixed_iso | fixed_spec | fixed_shed | lit_hedged | lit_retry | no_mitig |
|----------|----------|--------------|-----------|------------|------------|------------|-----------|----------|
| S2 | **30.0** | 30.5 | 30.3 | 31.9 | 33.6 | 61.3 | 61.3 | 67.2 |
| S3 | **39.3** | 41.1 | 39.9 | 41.0 | 39.2 | 68.8 | 68.7 | 73.3 |
| S4 | 43.8 | **37.4** | 37.6 | 54.6 | 69.3 | 110.9 | 108.8 | 125.1 |
| S5 | **30.3** | 30.5 | 30.6 | 31.2 | 31.1 | 34.5 | 34.5 | 34.6 |
| S6 | **32.8** | **32.8** | **32.8** | 35.0 | 37.0 | 110.6 | 110.2 | 125.7 |
| S7 | **29.7** | 30.5 | **29.7** | 29.8 | 29.9 | 32.3 | 32.3 | 32.3 |

## SLO Violation Rate (%)

| Baseline | S2 | S3 | S4 | S5 | S6 | S7 |
|----------|----|----|----|----|----|----|
| adaptive | 0.00 | 0.11 | 0.50 | 0.03 | 0.03 | 0.01 |
| lit_blacklist | 0.00 | 0.16 | **0.04** | 0.02 | 0.02 | 0.01 |
| fixed_isolation | 0.00 | 0.09 | 0.13 | 0.03 | 0.03 | 0.01 |
| lit_hedged | 1.19 | 1.74 | 3.41 | 0.72 | 1.92 | 0.41 |
| lit_retry | 1.20 | 1.71 | 3.41 | 0.71 | 1.91 | 0.41 |
| no_mitigation | 1.28 | 1.91 | 3.65 | 0.75 | 2.04 | 0.41 |

## Key Findings

### 1. Reactive Mechanisms Are Ineffective Against Persistent Slow Faults

lit_hedged and lit_retry provide marginal improvement over no_mitigation:
- SLO violation: 0.7-3.4% vs no_mitigation's 0.8-3.7% (< 0.3pp improvement)
- P99 reduction: 5-15ms (6-12%) vs no_mitigation
- P999: essentially identical to no_mitigation

Root cause: hedged requests are designed for random stragglers, not persistent
faults. They don't redirect future traffic — each request independently decides
whether to hedge. With persistent faults, the same nodes keep getting requests.

### 2. Proactive Detection + Exclusion Is the Effective Pattern

All three proactive approaches achieve P99 < 50ms across all scenarios:
- adaptive: 29.7-43.8ms
- lit_blacklist: 30.5-41.1ms
- fixed_isolation: 29.7-39.9ms

The common mechanism: detect faulty nodes, then stop routing to them.
Whether detection uses departure intervals (adaptive), latency outliers
(blacklist), or a fixed threshold (fixed_iso), the effect is similar.

### 3. Blacklist Beats Adaptive in S4 Multi-Node

lit_blacklist P99 = 37.4ms vs adaptive = 43.8ms (+17%)
lit_blacklist P999 = 44.8ms vs adaptive = 72.4ms (+62%)
lit_blacklist SLO violation = 0.04% vs adaptive = 0.50% (12.5x)

Root cause: blacklist makes binary decisions (in/out) with no escalation
delay. Adaptive's 4-stage escalation (SPECULATE→SHED→ISOLATE) introduces
per-node transition latency. With 4 simultaneous faults, this adds up.

### 4. fixed_isolation Is Surprisingly Strong

fixed_isolation ranks 1st-3rd in EVERY scenario with zero regressions:
- S2: 30.3ms (2nd)
- S3: 39.9ms (3rd)
- S4: 37.6ms (2nd)
- S5: 30.6ms (3rd)
- S6: 32.8ms (tied 1st)
- S7: 29.7ms (tied 1st)

This challenges the value proposition of the adaptive framework.

### 5. Three Clear Performance Tiers

Tier 1 (proactive, P99 < 45ms): adaptive ≈ lit_blacklist ≈ fixed_isolation
Tier 2 (reactive, P99 ≈ no_mitigation): lit_hedged ≈ lit_retry
Tier 3 (baseline): no_mitigation

## Implications for Paper

### Strong results:
- Reactive mechanisms (hedging/retry) are ineffective — clear, publishable negative result
- Proactive detection is necessary and sufficient
- The operating envelope formula (1-L/U) still holds

### Challenge to address:
- fixed_isolation is simpler and matches or beats adaptive in most scenarios
- Need to show scenarios where isolation's capacity cost becomes problematic
  (high load, many faults, partial degradation)

## Next Steps
- Run S4/S6 at higher loads (85-90%) where isolation's capacity removal hurts
- Compute minimax regret across scenarios to quantify robustness
- Add mixed-scenario experiment (sequential different fault types)
