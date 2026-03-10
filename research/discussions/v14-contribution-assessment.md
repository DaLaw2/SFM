# V14 Discussion: Research Contribution Assessment

**Date**: 2026-03-08
**Context**: V13 confirmed f_max = 1 - L/U; assessing overall research contributions and next steps.

---

## Background: V8-V13 Research Summary

| Version | Key Change | Result |
|---------|-----------|--------|
| V8 | 32 nodes, breaking point sweep (S8) | Discovered severity non-monotonicity (10x > 20x) |
| V9 | Capacity-theoretic analysis | Derived `f_max = 1 - L/U` operating envelope |
| V10 | Corrected P2C routing (weighted sampling) | Fixed overestimated avoidance; P2C leakage ~1/N not (1/N)² |
| V11 | Multi-metric evaluation framework | Added P999, goodput, tail ratio, affected_ratio |
| V12 | Breaking point analysis (S8 full matrix) | Mapped green/yellow/red zones across (f, s) space |
| V13 | Load sensitivity validation (S10) | Confirmed `f_max = 1 - L/U` at 4 load levels |

### Established Results
1. **Operating envelope formula**: `f_max = 1 - L/U` (U ≈ 0.92) — validated empirically
2. **Severity non-monotonicity**: 10x slowdown worse than 20x under P2C routing
3. **Three performance tiers** (from S11): proactive >> reactive ≈ no_mitigation
4. **Detection is necessary but not sufficient**: 6 versions of detector iteration proved S3 is a strategy problem

---

## Expert Panel Assessment

### Core Question: What Are the Research Contributions?

**Current state of contributions:**

| Contribution | Strength | Gap |
|-------------|----------|-----|
| Operating envelope `f_max = 1 - L/U` | Strong — validated at 4 load levels | Need formal proof, not just empirical |
| Adaptive framework (SPECULATE/SHED/ISOLATE) | Functional | No comparison with literature baselines |
| Severity non-monotonicity | Novel observation | No analytical formula — only empirical |
| Detection orthogonality insight | Strong narrative | Already well-documented |

### Key Challenge: fixed_isolation

**Problem**: `fixed_isolation` (simple threshold-based isolation) ranks 1st-3rd in EVERY scenario with zero regressions:

| Scenario | adaptive | fixed_isolation | Gap |
|----------|----------|----------------|-----|
| S2 | **30.0ms** | 30.3ms | +1% |
| S3 | **39.3ms** | 39.9ms | +2% |
| S4 | 43.8ms | 37.6ms | **-14% (iso wins)** |
| S5 | **30.3ms** | 30.6ms | +1% |
| S6 | **32.8ms** | **32.8ms** | tie |
| S7 | **29.7ms** | **29.7ms** | tie |

**Expert consensus**: The paper MUST convincingly answer "why not just use fixed_isolation?" Possible angles:
- High load (85-90%) where isolation's capacity removal causes cascade
- Many simultaneous faults where removing nodes causes overload
- Partial degradation (2-3x) where isolation is too aggressive
- Capacity cost: isolation wastes remaining capacity of degraded nodes

### Reactive vs Proactive: Clear Publishable Result

**Expert consensus**: The strongest publishable finding is the **negative result** — reactive mechanisms (hedged requests, timeout retry) are ineffective against persistent slow faults:
- SLO violation: 0.7-3.4% vs no_mitigation's 0.8-3.7% (< 0.3pp improvement)
- P99 reduction: only 5-15ms (6-12%)
- Root cause: hedging designed for random stragglers, not persistent faults

This directly challenges Dean & Barroso (2013) hedged requests for this fault class.

---

## Recommended Priority Tasks

### P0 — Must Do Before Paper

| Task | Description | Status |
|------|-------------|--------|
| P0a | Implement 3 literature baselines (hedged/blacklist/retry) | **COMPLETED** (V14, S11) |
| P0b | Derive severity non-monotonicity analytical formula | NOT STARTED |

**P0b detail**: Under P2C routing, the "worst severity" is not the highest slowdown but the one where `affected_ratio` crosses the `1 - percentile` threshold. Need closed-form expression for:
```
p_select(s) ≈ (1/N) × g(queue_ratio(s))
```
where `g` captures P2C's queue-depth avoidance. The worst severity `s*` satisfies:
```
f × p_select(s*) = 1 - percentile  (e.g., 0.01 for P99)
```

### P1 — Strengthening Results

| Task | Description |
|------|-------------|
| Minimax regret | Compute cross-scenario robustness metric for all baselines |
| Speculation catastrophe | Analyze S7 fixed_speculation P999=5784ms trigger conditions |
| High-load fixed_iso stress | Run S4/S6 at 85-90% load to show isolation capacity cost |

### P2 — Paper Writing

- Target venue: **SoCC** or **DSN**
- Narrative: "Proactive detection + exclusion is necessary and sufficient; reactive mechanisms fail; adaptive framework provides robustness across operating conditions"
- Must address fixed_isolation challenge head-on

---

## Expert Disagreements

| Topic | View A | View B |
|-------|--------|--------|
| fixed_isolation response | Show high-load scenarios where it fails | Reframe: adaptive = "smart isolation with graceful degradation" |
| Non-monotonicity priority | Critical for novelty — derive formula first | Nice-to-have — focus on practical comparison |
| Paper scope | Narrow: operating envelope + baseline comparison | Broad: include fan-out model (P1 from V7 discussion) |

## Consensus

1. **Literature comparison (P0a) is the #1 gap** — now filled by S11
2. **Severity non-monotonicity formula (P0b) is the strongest novelty claim** — needs analytical backing
3. **fixed_isolation challenge must be addressed** — either show failure modes or reframe contribution
4. **Three-tier result is publishable** — reactive << proactive, with quantitative evidence
5. **Operating envelope validated** — `f_max = 1 - L/U` holds across load levels
