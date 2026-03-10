# DR-003: Queue Model

**Date**: 2026-03-07
**Status**: Decided

## Context

Choose the queuing model for worker nodes in the simulator.

## Options

1. **M/D/1** - Poisson arrival, deterministic service, single server
2. **M/G/1** - Poisson arrival, general service time distribution
3. **M/D/1 + batch processing** - deterministic service with dynamic batching

## Decision

**Option 1: M/D/1 (start simple).**

## Rationale

- DNN inference has near-deterministic execution time (Clockwork, OSDI 2020 demonstrated this)
- M/D/1 naturally produces nonlinear tail latency as utilization -> 1.0, approximating the danger zone
- Simpler to implement, debug, and reason about
- Can upgrade to M/G/1 or add batching later if M/D/1 proves insufficient

## Risks

- M/D/1 may not capture all sources of variability in real inference systems
- Dynamic batching (vLLM, Orca) changes the service time distribution significantly
- Need to validate early: does M/D/1 reproduce danger-zone-like nonlinearity?

## Follow-up

- [ ] Run validation experiment comparing M/D/1 tail latency curve against ADR danger zone data
- [ ] If insufficient, upgrade to M/G/1 (DR to be created)
