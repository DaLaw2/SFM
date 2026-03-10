# Document Index

Documents are organized by progressive disclosure: start from overview, drill into details as needed.

## Level 1: Overview

| Document | Description |
|----------|-------------|
| `docs/overview.md` | Research motivation, gap, approach, and current status |
| `README.md` | Project structure and quick navigation |

## Level 2: Design

| Document | Description |
|----------|-------------|
| `docs/simulation-design.md` | Simulator architecture, queue model, fault injection, calibration, experiment parameters |
| `docs/experiments-guide.md` | How to run experiments, interpret results, and add new scenarios |
| `decisions/DR-*.md` | Individual design decisions with rationale |

## Level 2.5: Results

| Document | Description |
|----------|-------------|
| `experiments/results/REPORT.md` | Summary of all 7 experiment scenarios with metrics, findings, and cross-scenario analysis |

## Level 3: Deep Research

| Document | Key Contents |
|----------|-------------|
| `research/slow-fault-modeling.md` | IASO/Perseus/ADR fault models, severity quantification, simulation frameworks, GPU thermal modeling, public datasets |
| `research/inference-straggler-survey.md` | 30+ papers: Clipper, Clockwork, vLLM, DistServe, LATE, Mantri, CoCoI, FALCON; gap analysis |
| `research/slo-aware-analysis.md` | ADR danger zone details, SLO-aware scheduling (Shard Manager, Flux, TAPAS), control theory (PID, AIMD), graceful degradation (DAGOR) |
| `research/strategy-framework-design.md` | Full framework: system model, 3 strategies with parameters, decision algorithm pseudocode, AIMD weight controller, architecture diagram, 7 evaluation scenarios |

## Decision Records

| DR | Title | Date |
|----|-------|------|
| DR-001 | Paper type: simulation/analysis paper | 2026-03-07 |
| DR-002 | Simulator: SimPy + real data calibration | 2026-03-07 |
| DR-003 | Queue model: M/D/1 | 2026-03-07 |
| DR-004 | Initial scale: 16 nodes | 2026-03-07 |
| DR-005 | Strategy composition: SHED with optional hedging | 2026-03-07 |
| DR-006 | M/D/1 danger zone sufficiency confirmed | 2026-03-07 |
