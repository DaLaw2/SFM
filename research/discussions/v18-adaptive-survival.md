# V18 Discussion: PRISM Adaptive Framework Survival Analysis

**Date**: 2026-03-08
**Context**: After seed fix, adaptive framework shows no advantage over fixed_isolation; emergency review.

## Expert 1 — Systems Architect: Control Loop Analysis

### SHED-P2C Mechanism Conflict
P2C uses weights only for candidate sampling probability, then picks by queue depth. This creates oscillation:
- SHED reduces weight → fewer samples → queue drains → low queue depth → gets picked when sampled
- Net effect: weight reduction doesn't translate to proportional traffic reduction

### E1 Failure Path (8 nodes 2x, L=0.80)
- severity ≈ 0.5 (2x → σ = 1 - 1/2 = 0.5)
- G2 blocks isolation (ρ_eff = 0.914 > 0.92 after isolating 8)
- Falls back to SHED with weight ≈ 0.65-0.75
- Weak reduction disrupts P2C's natural balance without providing enough benefit

### E3 Failure Path (progressive 1x→8x)
- SHED phase delays ISOLATE activation by 1-2 seconds
- Graduated response is slower than fixed_isolation's direct isolation

### Conclusion
Problem is both fundamental (SHED conflicts with P2C mechanism) AND implementation-specific (debounce delay, AIMD too slow).

## Expert 2 — Queueing Theorist: SHED Value Analysis

### P2C Natural Load Balancing
Under P2C steady state, each node's load ≈ proportional to service rate (Mitzenmacher 2001). A node with slowdown s naturally receives ~1/s of normal traffic. **This is exactly what SHED tries to achieve.**

### When Could SHED Beat P2C?
Only during transients (P2C hasn't converged yet). But:
- P2C adaptation time: O(queue_depth × service_time) ≈ O(100ms)
- SHED detection time: 2 epochs × 0.5s = 1000ms
- **SHED is always 10x slower than P2C's natural adaptation**

### SHED's Dead Zone
- Light faults (s < 3x): P2C handles naturally, SHED is redundant
- Moderate faults (3-5x): P2C adapts in 150-250ms, faster than SHED's 1s detection
- Severe faults (s > 5x): ISOLATE is better
- **No severity range where SHED clearly wins**

### Exception
Only possible value: faults where isolation is infeasible (G2 blocks). But E1 data shows no_mitigation beats SHED even in this case.

## Expert 3 — Experimental Methodologist: S14 Fairness Review

### S14 Design Biases Against Adaptive
1. **Scale too small** (N=32): Isolation of 8 nodes = 25% capacity loss. At N=128, isolation of 8 = 6.25%.
2. **Duration too short** (60-100s): Single fault wave. Adaptive's value is in multi-wave/dynamic scenarios.
3. **Fault patterns too simple**: No recovery-then-refault, no rolling faults, no intermittent faults.
4. **Constant load**: No load fluctuation. Fixed_isolation struggles when capacity is tight during load peaks.

### Proposed Fair Experiments
- **F2: Multi-wave faults** (300s, 4 waves of different types)
- **F3: Intermittent faults** (10s on/10s off cycling)
- **F4: Non-stationary load** (sinusoidal L between 0.70-0.90) + faults
- **F5: Partial recovery** (8x → 2x, never fully recovers)

## Expert 4 — Paper Strategist: Positioning Options

### Option A: Pure Theory Paper
- Lead with operating envelope + severity non-monotonicity
- Risk: may be seen as "too simple" for full paper

### Option B: Robustness Paper
- "Detection is key, strategy choice is secondary"
- Clean finding but may lack depth

### Option C: Negative Result Paper
- "Graduated response is a myth under P2C"
- Needs very strong analysis

### Option D: Hybrid Paper (RECOMMENDED)
- Theory (envelope + non-monotonicity) as primary
- Departure-interval detection as technique contribution
- LOR herd behavior as surprise finding
- "Proactive detection suffices" as practical conclusion

### Option E: Redefine Adaptive's Value
- "Never catastrophically fails" (unlike lit_blacklist)
- Weaker claim but defensible

## Expert 5 — Devil's Advocate: Challenging "No Advantage" Conclusion

### Challenge 1: SHED Weight Formula Is Wrong
Current formula is linear, but P2C's sampling is nonlinear. A weight of 0.5 doesn't mean 50% less traffic. Need P2C-aware weight formula.

### Challenge 2: AIMD Is Too Slow
alpha=0.05 → recovery from w_min to 1.0 takes 28.5 seconds. In 60s experiments, AIMD never converges.
Fix: alpha=0.15, stable_threshold=1 → recovery in 2.5s.

### Challenge 3: spare_factor=0.3 May Be Wrong Fix
At high load, ANY weight reduction hurts. The 0.3 floor means SHED intervenes when it shouldn't. Revert to 0.0.

### Challenge 4: High-Severity Zero Debounce
For severity > 0.4, skip persistence confirmation. Reduces detection to 0.5s.

### Challenge 5: Adaptive's Value May Be Under LOR, Not P2C
V17 data: LOR+fixed_iso in S4 = 104.4ms, but LOR+adaptive = 51.2ms. Adaptive partially mitigates LOR's herd behavior.

## Panel Verdict: MAYBE — Conditional

Adaptive is not fundamentally impossible to save, but requires:
1. Fixing SHED-P2C mechanism conflict
2. Detection latency < 0.5s for high severity
3. Demonstration in dynamic scenarios (multi-wave, intermittent, non-stationary)
4. Expected improvement: at most 5-15%

**Time budget:** 2 days max. If no >10% improvement in any fair scenario, abandon adaptive as system contribution.

## Top 5 Research Directions (Ranked)

1. **P2C-aware SHED weights**: Derive exact weights for target traffic fraction under weighted P2C
2. **Multi-wave/dynamic fault experiments**: F2-F5 designs
3. **SHED as probabilistic exclusion**: Replace weight adjustment with per-epoch probabilistic exclusion
4. **Detection latency optimization**: CUSUM/EWMA detectors, zero debounce for high severity
5. **Adaptive under LOR**: V17 data suggests adaptive's real value is under LOR, not P2C
