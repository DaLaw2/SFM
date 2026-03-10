# DR-001: Paper Type

**Date**: 2026-03-07
**Status**: Decided

## Context

Need to decide whether this is a systems paper (requiring prototype + real deployment) or an analysis/simulation paper.

## Options

1. **Systems paper** (target OSDI/SOSP/NSDI) - requires full implementation + real cluster experiments
2. **Analysis/simulation paper** (target SIGMETRICS/Performance/MASCOTS) - simulation-based evaluation

## Decision

**Option 2: Analysis/simulation paper.**

## Rationale

- Building a full prototype integrated with real inference engines (vLLM/Triton) is a large engineering effort that would delay the core research contribution
- The primary contribution is the multi-strategy selection framework and its analysis, not a production system
- Simulation allows systematic exploration of the parameter space (fault severity, workload, scale) that would be difficult with a real system
- Can always build a prototype later as follow-up work

## Consequences

- Must ensure simulation fidelity via calibration against real data (Perseus, ADR, TAPAS)
- Need strong baselines and comprehensive scenarios to compensate for lack of real-system evaluation
- Target venues: SIGMETRICS, Performance, MASCOTS, or similar
