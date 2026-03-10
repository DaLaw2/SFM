# V18 Findings: Adaptive Framework Has No Genuine Performance Advantage

**Date**: 2026-03-08

## Experiments and Results

### E1: Many Moderate Faults (8 nodes at 2x, isolation infeasible)

| Baseline | L=0.70 | L=0.75 | L=0.80 | L=0.85 |
|---|---|---|---|---|
| no_mitigation | 57.7 | 64.3 | **76.3** | 106.4 |
| fixed_isolation | 43.1 | 56.1 | 81.7 | **214.4** |
| adaptive | 43.1 | 56.2 | 95.7 | **193.1** |
| lit_blacklist | **41.1** | 209.5 | 3087.8 | 5790.2 |

**Surprise:** At L=0.80, no_mitigation (76.3ms) beats both active strategies. P2C naturally routes proportionally to capacity — 2x nodes get ~half the traffic. Active intervention (SHED weight reduction) disrupts this natural balance.

### E2: Mixed Severity (6 nodes: 2x8x + 2x3x + 2x1.5x)

| Baseline | L=0.75 | L=0.80 | L=0.85 |
|---|---|---|---|
| no_mitigation | 183.9 | 146.3 | 175.6 |
| fixed_isolation | **38.1** | 109.0 | 175.6 |
| adaptive | 37.8 | 120.4 | 175.6 |
| lit_blacklist | 38.7 | **67.7** | 766.9 |

**fixed_iso beats adaptive** at L=0.80 (109 vs 120ms). The graduated strategy provides no benefit.

### E3: Progressive Degradation (4 nodes, 1x→8x over 30s)

| Baseline | L=0.75 | L=0.80 | L=0.85 |
|---|---|---|---|
| no_mitigation | 220.9 | 241.3 | 283.5 |
| fixed_isolation | **31.5** | 111.3 | 271.4 |
| adaptive | 31.5 | 180.9 | 280.3 |
| lit_blacklist | 31.7 | **37.6** | **52.7** |

**lit_blacklist dominates.** adaptive is consistently worst among proactive strategies.

## Root Cause Analysis

### Why SHED Hurts More Than Helps

For moderate faults (2x slowdown), P2C already routes proportionally to capacity:
- Healthy node: capacity μ, gets proportional share
- 2x node: capacity μ/2, gets half the share via queue-depth avoidance

SHED explicitly reduces weights, but this over-corrects:
1. Weight reduction pushes more traffic to healthy nodes
2. Healthy nodes approach saturation → queueing delay spikes
3. Net effect: worse than doing nothing

This is validated by E1 at L=0.80: no_mitigation (76.3ms) < fixed_iso (81.7ms) < adaptive (95.7ms).

### Why Adaptive Has No Advantage Over Fixed Isolation

1. **High severity faults (≥5x):** Both strategies choose ISOLATE. No difference.
2. **Moderate severity faults (2-3x):** adaptive chooses SHED, fixed_iso attempts ISOLATE → G2 downgrades to SHED with same weight formula. Effectively same behavior.
3. **Low severity faults (1.5x):** Neither strategy does much. P2C handles it.
4. **AIMD tuning:** AIMD's additive increase (0.05/epoch) is too slow to converge before the system reaches steady state through other mechanisms.

### The Fundamental Issue

The paper's adaptive framework (SPECULATE → SHED → ISOLATE) assumes that graduated response adds value. The data shows it doesn't, because:
- **Detection latency dominates:** By the time any strategy acts (1s debounce), the damage is done
- **P2C already implements graduated response:** Queue-depth avoidance naturally reduces traffic to slow nodes, proportional to severity
- **SHED is redundant with P2C:** Explicit weight reduction duplicates what P2C does implicitly, with added overhead

## What the Paper Should Claim

### Claims That ARE Supported

1. **Operating envelope** (f_max = 1 - L/U): Validated, fundamental, novel
2. **Severity non-monotonicity** (s* formula): Validated, counterintuitive, novel
3. **Reactive vs proactive gap**: Massive and consistent (30-90ms difference)
4. **Proactive detection is necessary and sufficient**: Any proactive strategy (isolation, blacklist, adaptive) dramatically outperforms reactive
5. **lit_blacklist catastrophic failure mode**: Consistent at high load or many faults
6. **LOR synchronization failure under isolation**: Novel finding

### Claims That Are NOT Supported

1. ~~"Adaptive outperforms static isolation by 25-33% at high load"~~ — Seed artifact
2. ~~"Graduated strategy selection provides best worst-case performance"~~ — No evidence
3. ~~"SHED preserves partial capacity from degraded nodes"~~ — SHED is counterproductive

### Recommended Paper Repositioning

**Option A: Theory-First Paper**
- Lead with operating envelope and severity non-monotonicity as primary contributions
- Evaluation demonstrates the theory's predictive power
- Strategy comparison becomes secondary: "any proactive strategy suffices"
- Remove adaptive framework as a contribution; simplify to "proactive detection + isolation"

**Option B: Robustness Paper**
- Redefine adaptive's value as "never catastrophically fails"
- lit_blacklist catastrophically fails at high load / many faults
- fixed_isolation has no fallback when G2 blocks isolation
- adaptive gracefully degrades (doesn't win, but doesn't catastrophically lose)
- Weaker claim but still defensible

**Recommendation: Option A.** The theory is the strongest and most novel part. The adaptive framework adds complexity without demonstrated benefit. A simpler paper with stronger claims is better than a complex paper with unsupported claims.
