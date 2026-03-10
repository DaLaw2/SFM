# Research Overview

## Problem

Distributed systems experience "slow faults" (fail-slow): nodes that remain alive but operate at degraded performance. These are hard to handle because heartbeats pass normally, so fault recovery never triggers, yet throughput silently degrades.

## Gap

- **Detection is solved**: IASO (ATC'19), Perseus (FAST'23), ADR (NSDI'25) can detect slow faults.
- **Mitigation is not**: All existing responses are single fixed strategies:
  - IASO: reboot or shutdown (binary)
  - MapReduce literature: speculative execution only
  - Cloud practice: replace the instance (coarse-grained)
- **No existing work dynamically selects among multiple strategies based on fault severity and SLO distance.**

## Approach

A framework with three mitigation strategies, selected adaptively:

| Strategy | When | Cost |
|----------|------|------|
| Speculative execution | Low severity, spare capacity available | Extra compute |
| Load shedding (AIMD) | Moderate severity | Wasted slow-node capacity |
| Isolation + probe | High severity | Lost node capacity |

Key mechanisms:
- SLO-distance-driven adaptive thresholds (tighten as SLO violation approaches)
- Danger-zone-aware preemptive escalation (from ADR's finding)
- AIMD-based recovery (gradual reintegration of recovered nodes)
- Hysteresis + debounce to prevent strategy oscillation

## Target Scenario

Distributed inference serving (stateless requests, clear latency SLOs, real GPU performance variance).

## Method

Simulation study using SimPy discrete-event simulator with M/D/1 queue model, calibrated against real data (Perseus dataset, ADR danger zone measurements, TAPAS thermal model).

## Current Status

- [x] Literature survey (30+ papers)
- [x] Framework design with pseudocode
- [x] Evaluation plan (6 baselines, 11 metrics, 7 scenarios)
- [x] Simulator implementation
- [x] Experiments (7 scenarios completed: S1-S7)
- [ ] Paper writing

## Key References

| Paper | Venue | Role in our work |
|-------|-------|-----------------|
| ADR (Lu et al.) | NSDI'25 | Danger zone concept; detection front-end |
| IASO (Panda et al.) | ATC'19 | Baseline: binary mitigation |
| Perseus (Lu et al.) | FAST'23 | Severity metric (slowdown ratio); public dataset |
| Fail-Slow at Scale (Gunawi et al.) | FAST'18 | Fault taxonomy; 4 temporal patterns |
| Dean & Barroso | CACM'13 | Hedged requests foundation |
| TAPAS (Qiu et al.) | ASPLOS'25 | GPU thermal throttling model |
| DAGOR (Zhou et al.) | SoCC'18 | Priority-based load shedding |
