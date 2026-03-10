# DR-007: Base Service Time = 10ms

**Date**: 2026-03-07
**Status**: Decided

## Context

Original simulation-design.md specified `t_base = 20ms` (typical DNN inference). But with M/D/1 single-server model, per-node capacity = `1/t_base`. To match the spec's 100 req/s per worker, `t_base` must be 10ms.

## Decision

**`t_base = 0.01` (10ms).**

## Rationale

- M/D/1 with single server: max throughput = `1/t_base = 100 req/s` per node
- The 20ms figure from literature includes queueing delay, not just service time
- 10ms pure service time + queueing delay ≈ 20ms observed latency at moderate load
- Smoke test confirms: avg latency 13.3ms, P99 26.9ms at 70% load — realistic

## Consequence

- SLO target remains 100ms (P99), which is ~10x base service time — reasonable headroom
- Danger zone analysis unchanged: `rho = 0.7` at `s = 1.43` still hits `rho' = 1.0`
