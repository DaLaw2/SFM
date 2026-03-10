# DR-002: Simulator Choice

**Date**: 2026-03-07
**Status**: Decided

## Context

Need a simulation platform for evaluating the adaptive strategy selection framework.

## Options

1. **Custom SimPy simulator** + calibration with real data
2. **Slooo framework** (UIUC) - real system fault injection on RethinkDB/MongoDB
3. **CloudSim / ns-3** - existing cloud/network simulators

## Decision

**Option 1: Custom SimPy discrete-event simulator, calibrated with real data from Perseus, ADR, and TAPAS.**

## Rationale

- SimPy is mature, well-documented, and allows full control over all components
- No existing simulator natively supports parametric slow-fault modeling
- Slooo targets storage systems, not inference; heavy adaptation needed
- CloudSim/ns-3 lack slow-fault models entirely
- Calibration with real data (Perseus slowdown ratios, ADR danger zone measurements, TAPAS thermal curves) provides grounding without requiring real hardware
- Model validation: reproduce ADR's danger zone phenomenon in simulation as a sanity check

## Consequences

- Must implement all components from scratch (queue model, fault injection, strategy logic, metrics)
- Must justify model fidelity in the paper via calibration and validation
- Estimated effort: 1-2 weeks for core simulator
