# V05 Discussion: Expert Insights

**Date**: 2026-03-08
**Context**: After V2-V5 iterations, three expert perspectives consulted to identify the right path forward.

## Expert Panels

### Queueing Theory Expert

**Key insight: Departure interval service time estimation.**

In M/D/1 queues under high load, inter-departure times converge to the
actual service time `d`. By computing the P10 of inter-departure intervals
per node per epoch, we get a load-invariant estimate of service time.

- Healthy node: departures every ~10ms regardless of load → d_est = 10ms
- Faulty node (2x): departures every ~20ms regardless of load → d_est = 20ms
- Severity: `max(0, 1 - t_base / d_est)`

This signal is completely unaffected by queueing delay, making it immune to
the S3 false-positive problem (high latency from load, not fault) and the
S6 guard-blowup problem (M/D/1 expected latency diverges at high rho).

Also proposed: capacity-aware continuous weight optimization (`w_i ∝ 1/d_i`)
instead of discrete strategies at high load, and spare-rate circuit breaker
for load transients.

### Control Systems Expert

**Key insight: The de-escalation mechanism uses the same time constant for
two fundamentally different situations.**

- Fault recovery: severity drops because node healed → slow de-escalation correct
- Load transient: severity drops because all nodes uniformly slow → need instant de-escalation

Proposed solutions (by priority):
1. **P0: Asymmetric EMA** (α_down=0.7, α_up=0.2) — spare_capacity tracks
   load increases in 0.42s instead of 1.4s
2. **P0: SHED weight decay with spare** — `spare_factor = spare/0.20`,
   SHED weight → 1.0 at high load, eliminating side effects
3. **P1: Fast de-escalation** — when d_spare < -0.05, bypass debounce
4. **P2: Disturbance observer** — compute expected latency from known weights
   and arrival rate, use residual as severity (decouples detection from
   mitigation effects)

Also identified the feedback coupling: SHED → load redistribution →
median rises → severity drops → de-escalation → load returns → severity
rises → SHED again (limit cycle). EMA and debounce mask this oscillation
but don't eliminate it.

### Distributed Systems Expert

**Key insight: Detection is over-engineered. The real problem is in the
strategy layer.**

V2-V5 all modified the detector, but S3 was never fixed. The fix is not
a better detector but a **mitigation budget**:

```
budget = max(0.0, min(1.0, (spare - 0.08) / 0.15))
effective_severity = raw_severity * budget
```

At rho > 0.92, budget → 0, all mitigation disabled. This is not "giving up"
— P2C already provides strong implicit mitigation at high load (queue-aware
routing amplifies avoidance of slow nodes as rho → 1).

Also proposed paper framing: "capacity-safety tradeoff" as core thesis,
with the 5-version iteration as design space exploration.

## Cross-Expert Convergence

All three experts independently concluded:
1. **S3 is a strategy/control problem, not a detection problem**
2. **Some form of load-aware mitigation suppression is needed at high rho**
3. **P2C provides implicit mitigation that explicit strategies should not override**

## User Discussion: Re-evaluating Research Direction

After expert discussion, a critical re-evaluation:

**The "Mitigation Trap" (overload + mitigation = worse) is intuitive, not novel.**
Anyone with distributed systems experience would expect this.

**More genuinely non-obvious findings:**

1. **P2C's implicit mitigation dominates explicit strategies at high load** —
   counterintuitive because "doing something" is expected to beat "doing nothing",
   but P2C's queue-aware routing automatically amplifies avoidance as rho → 1.

2. **Detector improvements cannot fix strategy-layer problems** — V2-V5 all
   modified the detector; S3 was never solved. The problem is not "detecting
   faults at high load" but "what to do about detected faults at high load."

3. **No single detector dominates across all scenarios** — V4 best for S4,
   V5 best for S6, V3 best for S3. This suggests runtime adaptation of the
   detection mechanism itself, not just the mitigation strategy.

4. **Departure interval service time estimation** — a theoretically novel
   detection signal that is load-invariant. Unlike P99-based detection
   (polluted by queueing delay) or M/D/1 guards (blow up at high rho),
   departure intervals directly measure what we care about: has the node's
   service time changed?

## Decision: Next Steps

Two candidate directions identified:

### A: Mitigation Budget (minimal change)
Add `severity *= budget` in selector. Simplest possible fix for S3.
Does not improve detection but prevents harmful intervention at high load.

### B: Departure Interval Detection (larger change)
Replace P99-based detection with service-time estimation from departure
intervals. Requires changes to monitor (collect completion timestamps),
detector (new estimation logic), and possibly worker (expose departure data).
Potentially solves S3/S4/S6 simultaneously with a single unified mechanism.

**Decision: Try B (departure interval).** Larger change but addresses the
root cause rather than patching symptoms. The mitigation budget can be added
later as defense-in-depth if needed.
