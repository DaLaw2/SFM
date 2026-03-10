# DR-006: M/D/1 Danger Zone Sufficiency

**Date**: 2026-03-07
**Status**: Decided

## Context

Can M/D/1 queue model reproduce the "danger zone" nonlinearity observed by ADR in real systems?

## Analysis

M/D/1 average waiting time: `W = rho / (2 * mu * (1 - rho))`

With slowdown factor `s`, effective utilization becomes `rho' = rho * s`.

Example at 70% base load (`rho = 0.7`):
- `s = 1.0` -> `rho' = 0.70` -> normal
- `s = 1.2` -> `rho' = 0.84` -> moderate latency increase
- `s = 1.4` -> `rho' = 0.98` -> latency explosion
- `s = 1.43` -> `rho' = 1.0` -> queue diverges

The danger zone is approximately `s in [1.2, 1.43]` — a narrow range where small severity increases cause disproportionate latency growth. This matches ADR's observation of narrow danger zones.

## Decision

**M/D/1 is sufficient for initial experiments.**

## Key Insight

Our framework's goal is to push the danger zone boundary rightward — tolerating higher per-node severity before the system-level performance cliff, by redistributing load before the node's queue diverges. M/D/1 naturally creates this cliff effect.

## Follow-up

- [ ] Validate numerically in early simulation runs
- [ ] If results look unrealistic, upgrade to M/G/1 (new DR)
