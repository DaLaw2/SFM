# DR-009: GPU Control Plane Probe-Based Recovery

**Date**: 2026-03-08
**Status**: Decided (validated, reviewed, revised)

## Context

The GPU simulator uses an epoch-based control plane (0.5s epochs). After each
epoch, the CPU-side ControlBridge extracts departure intervals from GPU state,
runs the Detector/Selector/AIMD pipeline, and updates weights/exclusion masks.

When a faulted node is isolated (weight=0, excluded=True), it receives no
traffic and produces ~0-2 departures per epoch — below the Detector's
MIN_INTERVALS=5 threshold. This creates an **observability paradox**: the
isolation action destroys the signal needed to maintain the isolation decision.

## Problem: Isolation Oscillation

Two failure modes were observed:

1. **No data guard**: severity=0 (insufficient data misread as healthy) →
   immediate un-isolation → re-detection → re-isolation. Limit cycle with
   ~2s period. Faulted nodes isolated only ~1/3 of the time.
   Result: P99=82ms (vs CPU SimPy 35.9ms for 3-node 3x fault).

2. **Strict data guard**: require MIN_INTERVALS before un-isolating → isolated
   nodes never accumulate enough data → permanent lockout. Combined with
   max_isolation_fraction rotation, queues explode.
   Result: P99=499ms.

## Decision: Periodic Single-Node Probe with Probation

Isolated nodes are fully excluded (weight=0) most of the time. Periodically,
**one node at a time** receives a small probe weight for one epoch to collect
diagnostic data. Recovered nodes go through a probation period.

### Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `PROBE_WEIGHT` | 0.14 | ~5 arrivals during probe epoch |
| `MIN_HOLD_EPOCHS` | 4 | 2s minimum isolation before first probe |
| `PROBE_INTERVAL` | 8 | 4s between probes per node |
| `RECOVERY_CONFIRM` | 2 | Consecutive healthy probes to un-isolate |
| `PROBE_THETA` | 0.15 | Aligned with SimPy's theta_recovery=0.15 |
| `PROBATION_WEIGHT` | 0.5 | Reduced weight during post-recovery probation |
| `PROBATION_EPOCHS` | 4 | 2s gradual reintegration after recovery |
| `_max_isolated` | N/4 | Capacity budget for simultaneous isolations |

### Algorithm

1. **Isolation with capacity budget**: When Selector assigns ISOLATE, check
   `len(_isolated_nodes) < _max_isolated` before adding. Excess nodes fall
   back to SHED weight. Once isolated, the bridge overrides Selector decisions
   to prevent oscillation from budget rotation.

2. **Periodic probe**: Every `PROBE_INTERVAL` epochs, set weight=PROBE_WEIGHT
   for **one** isolated node. Nodes are selected by earliest scheduled probe
   time (fair round-robin, not biased by node ID).

3. **Probe evaluation**: Compute severity using **median** of departure
   intervals (not P10), which is robust with small sample sizes (~5 values).
   Compare against `PROBE_THETA=0.15` (aligned with SimPy's theta_recovery).
   Bypasses the Detector's CONFIRM_EPOCHS — the fault was already confirmed.

4. **Recovery with probation**: After RECOVERY_CONFIRM consecutive healthy
   probes, reintegrate at PROBATION_WEIGHT=0.5 for PROBATION_EPOCHS=4. This
   catches oscillating faults that happen to be healthy during probe epochs.
   Reset `detector._consecutive[wid]=0` for clean re-detection if needed.

### Fixes Applied (from code review)

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 1 | HIGH | Override bypasses Selector isolation budget — monotonic ratchet | Added `_max_isolated = N/4` cap on simultaneous isolations |
| 2 | HIGH | Fluctuating fault phase-alignment → false recovery | Added 4-epoch probation at reduced weight after recovery |
| 3 | HIGH | P10 on ~5 intervals statistically unreliable | Changed to median (robust with small N) |
| 4 | HIGH | `departure_buf_size=50` at capacity boundary | Increased to 128 in GPUConfig |
| 5 | MEDIUM | Recovery threshold: SimPy 0.15 vs GPU 0.3 | Added `PROBE_THETA=0.15` aligned with SimPy |
| 6 | MEDIUM | Selector/Detector state drift during isolation | Reset `detector._consecutive` on recovery |
| 7 | MEDIUM | Probe severity uses P10 vs SimPy's mean(latency) | Changed to median (≈mean for isolated nodes with no queueing) |
| 8 | MEDIUM | No transition period after recovery | Added probation (PROBATION_WEIGHT=0.5, 4 epochs) |

### Second-Round Review Fixes

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 9 | HIGH | Probation block ran after isolation override, setting weight=0.5 for re-isolated nodes | Moved probation before isolation override; probation respects SHED/ISOLATE escalation; isolation override cleans up `_probation_nodes` |
| 10 | MEDIUM | Recovery count reset on Poisson variance (44% of probes yield <5 intervals) | Changed insufficient-data handling from reset to no-op; only reset on confirmed-still-faulted |

Accepted differences (not bugs):
- Probe frequency: SimPy 30s vs GPU 4s — SimPy operates in continuous time with recovery
  probes running alongside normal traffic; GPU's epoch-based control uses shorter intervals
  appropriate for its discrete structure.
- Recovery confirm: SimPy 1 vs GPU 2 — GPU's RECOVERY_CONFIRM=2 is more conservative,
  appropriate given the small sample size (~5 intervals) per probe epoch.

### Probe Round-Robin Fairness

Changed from `sorted(self._isolated_nodes)` (biased toward low IDs) to sorting
by `_probe_epoch` value (earliest-scheduled first). Ensures all isolated nodes
get probed at equal frequency regardless of node ID.

### Validation Results

Base validation (no mitigation): 10/10 tests pass.
Control plane validation (mitigation enabled): 4/4 tests pass.

| Scenario | CPU P99 | GPU P99 | Diff |
|----------|---------|---------|------|
| perm 2x (3 seeds) | 27.6-28.3ms | 27.7-28.5ms | ≤1.0ms |
| perm 5x (2 seeds) | 27.6-28.3ms | 28.6-28.8ms | ≤1.0ms |
| multi-node 3x | 35.9ms | 37.5ms | +1.6ms |

## Known Limitations

- **Fluctuating faults with period = 2×PROBE_INTERVAL**: Probes could
  systematically land on healthy phases. Probation mitigates but doesn't
  fully prevent this for long-period oscillations.
- **Recovery latency**: MIN_HOLD + PROBE_INTERVAL + RECOVERY_CONFIRM probes
  = ~6-10s minimum. Acceptable for this simulator.
- **Many-node faults**: With `_max_isolated = N/4`, at most 4 of 16 nodes
  can be isolated. Additional faulted nodes get SHED treatment.
