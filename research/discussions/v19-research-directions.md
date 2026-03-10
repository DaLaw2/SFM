# V19 Discussion: Alternative Research Directions

**Date**: 2026-03-08
**Context**: Three experts explored research directions after V18 confirmed adaptive framework has no advantage.

## Expert Panel Composition

1. **Queueing Theory Expert** — formal analysis, theoretical contributions
2. **ML/Statistics Detection Expert** — detection algorithms, streaming architecture
3. **Distributed Systems Expert** — practical directions, production system integration

---

## Tier 1: High-Impact, Low-Risk Directions (Do First)

### Direction 1: Retry Amplification Under Slow Faults
**Source:** Distributed Systems Expert (Direction A)
**Novelty:** Very High | **Effort:** 2-3 weeks

Every production system has retry. But retry is designed for crash faults (node dies, retry elsewhere succeeds). Under slow faults, retry creates a fatal positive feedback loop:

- Slow node → timeout → retry → increased global arrival rate → healthy nodes saturate → more timeouts → more retries

**Modified operating envelope:**
```
L_eff = L × (1 + r × p_timeout)
f_max(r) = 1 - L_eff / U = 1 - L(1 + r × p_to) / U
```

Concrete prediction (N=32, L=0.80, s=5x):
| Retry budget | L_eff | f_max | Max faults |
|---|---|---|---|
| r=0 | 0.80 | 10.0% | 3.2 |
| r=1 | 0.822 | 7.5% | 2.4 |
| r=2 | 0.845 | 5.0% | 1.6 |
| r=3 | 0.867 | 2.5% | 0.8 |

**One retry halves fault tolerance.** This is counterintuitive and practically important.

Also connects to circuit breaker analysis — CB's half-open state creates the same oscillation as lit_blacklist (V16 finding).

**Implementation:** Add retry logic to RequestGenerator, sweep retry×fault×load.

### Direction 2: Unified Phase Diagram
**Source:** Distributed Systems Expert (Direction E) + Queueing Theory Expert
**Novelty:** Medium-High | **Effort:** 2-3 weeks

Unify all existing formulas into a single multi-dimensional phase diagram:
- **Capacity boundary:** f_max(L) = 1 - L/U (horizontal)
- **Visibility boundary:** s*(f, N, q) curve
- **Retry boundary:** L_eff(r) = U curve
- **Variability dimension:** C_s² shrinks the safe zone (M/D/1 vs M/M/1)

Three phases: Safe (P2C handles it) → Degraded (proactive isolation needed) → Failed (beyond envelope).

Mostly theoretical + visualization. Minimal simulator changes.

### Direction 3: SHED Redundancy Theorem (Negative Result as Contribution)
**Source:** Queueing Theory Expert (Direction 1)
**Novelty:** High | **Effort:** 1-2 weeks

Formalize V18's finding as a theorem:

> **Theorem (SHED Redundancy):** Under P2C(d=2) routing with queue-depth comparison, for any severity s and weight function w(s), the steady-state traffic fraction to a faulty node under SHED differs from P2C's natural traffic fraction by O(1/N).

Proof sketch: P2C's natural routing already sends ~1/s fraction to a node with slowdown s (Mitzenmacher 2001). SHED's weight reduction is redundant because P2C's queue-depth comparison dominates the weight-based sampling probability.

This turns the "negative result" into a positive theoretical contribution: we proved WHY graduated response can't work under P2C.

---

## Tier 2: High-Impact, Medium-Risk Directions

### Direction 4: P2C as Implicit Fault Mitigator — Quantitative Analysis
**Source:** Distributed Systems Expert (Direction C) + Queueing Theory Expert
**Novelty:** Very High | **Effort:** 3-4 weeks

P2C's fault tolerance has never been formally analyzed. Key sub-questions:

**C1: Transient convergence time.** How long does P2C take to redistribute traffic after fault onset? Estimated O(100ms) but unproven. Measure traffic split at 10ms granularity.

**C2: Optimal d value.** d=2 gives 98.4% healthy candidate probability at f=4/N=32, but only 93.75% at f=8/N=32. d=3 improves to 98.44%. But V17 proved LOR (d=N) causes herd behavior. There exists an optimal d* balancing fault tolerance and herd avoidance.

**C3: Fault-aware score function.** Replace `score = queue_depth` with `score = queue_depth + α × ewma_service_time / t_base`. This merges detection and routing into per-request operation — no control loop needed.

### Direction 5: CUSUM Streaming Detection (Reviving Adaptive's Case)
**Source:** ML/Statistics Detection Expert
**Novelty:** High | **Effort:** 2-3 weeks

Key insight: current detection bottleneck is the 500ms epoch architecture, not the detection algorithm. CUSUM can detect in 30-50ms per sample if architecture is streaming.

If detection latency < 100ms (P2C's natural adaptation time), then explicit mitigation acts BEFORE P2C adjusts → adaptive has a genuine advantage during the transient.

**Critical requirement:** Must move from epoch-based to streaming architecture:
- Current: accumulate stats for 500ms → analyze → decide → act (1000ms+ total)
- Streaming: each response triggers incremental CUSUM update → immediate decision when threshold crossed

**Risk:** Even with 30-50ms detection, the advantage window is small (50-100ms). Whether this translates to measurable P99 improvement depends on arrival rate during that window.

### Direction 6: Deadline Propagation as Per-Request Adaptive Isolation
**Source:** Distributed Systems Expert (Direction B)
**Novelty:** High | **Effort:** 2-3 weeks

Each request carries `deadline = SLO - elapsed_time`. Worker checks if `estimated_service_time > remaining_deadline` → early reject + reroute.

Key properties:
- **No detection delay:** Per-request decision, no statistics accumulation
- **Auto-calibrated:** Severe fault → more rejects → approaches isolation
- **No P2C disruption:** P2C routes normally; only the worker decides to reject

This is exactly what SHED wanted to achieve but couldn't: selective capacity preservation for moderate faults. Unlike SHED (which adjusts routing weights and disrupts P2C balance), deadline propagation lets each request self-select.

---

## Tier 3: Valuable but Higher Effort

### Direction 7: Information-Theoretic Detection Delay Lower Bound
**Source:** Queueing Theory Expert (Direction 2)
**Novelty:** Very High | **Effort:** 3-4 weeks

Derive minimum samples needed to distinguish slowdown s from normal variation at confidence level α. For M/D/1 (C_s²=0), detection is trivial (any single sample above t_base). For M/M/1 (C_s²=1), need ~O(1/s²) samples due to natural variance.

This connects to the severity non-monotonicity finding: at s*, the fault becomes P99-visible, which is also when statistical detection becomes reliable.

### Direction 8: Kubernetes/Envoy Gap Analysis
**Source:** Distributed Systems Expert (Direction D)
**Novelty:** Medium | **Effort:** 4-5 weeks

Envoy outlier detection cannot detect slow faults (only 5xx errors and success rate). Our departure-interval detection solves this (load-invariant severity estimation). Could be packaged as Envoy WASM filter.

Also: control plane propagation delay (1.5-3.5s in production) further widens the gap between detection and mitigation.

High practical impact but engineering-heavy.

---

## Recommended Paper Repositioning

### Title Direction
> "Operating Envelope of Slow Fault Tolerance Under Power-of-Two-Choices Load Balancing"

### Narrative Arc
1. **Theory:** Operating envelope + severity non-monotonicity + SHED redundancy theorem
2. **Interactions:** Retry amplification (shrinks envelope), deadline propagation (new mechanism)
3. **Evaluation:** Phase diagram validation, P2C transient analysis, strategy comparison
4. **Practical:** Capacity planning formulas, Envoy gap analysis

### Execution Priority (Time-Constrained)

| Priority | Direction | Weeks | Cumulative |
|---|---|---|---|
| **P0** | D3: SHED redundancy theorem | 1-2 | 1-2 weeks |
| **P1** | D1: Retry amplification | 2-3 | 3-5 weeks |
| **P2** | D2: Phase diagram | 2-3 | 5-8 weeks |
| **P3** | D4: P2C quantitative analysis | 3-4 | 8-12 weeks |
| **P4** | D5: CUSUM streaming | 2-3 | 10-15 weeks |
| **P5** | D6: Deadline propagation | 2-3 | 12-18 weeks |

**Minimum viable paper (4-5 weeks):** D3 + D1 + D2
**Strong paper (8-10 weeks):** Add D4
**Full paper (12+ weeks):** Add D5 + D6

### Key Insight Across All Experts

All three experts converged on the same meta-conclusion:

> **P2C is not just a load balancer — it is an implicit fault mitigator.** The paper's contribution should shift from "here's a better mitigation strategy" to "here's why you don't need one (under P2C), and here's what actually matters (detection speed, retry control, capacity planning)."

This reframing turns every "negative result" into a positive finding:
- SHED is redundant → **Theorem:** P2C subsumes graduated response
- Adaptive has no advantage → **Finding:** Detection speed matters, strategy choice doesn't
- Retry makes things worse → **Contribution:** Modified operating envelope with retry
- LOR fails under isolation → **Finding:** Randomized routing is essential for fault tolerance
