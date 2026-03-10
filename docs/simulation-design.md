# Simulation Design

## Simulator Choice

**SimPy** (Python discrete-event simulation library) + custom implementation.

Rationale: No existing simulator natively supports parametric slow-fault modeling. SimPy provides the event-driven core; we build the domain logic on top. See DR-002.

## Queue Model

**M/D/1** per worker node (Poisson arrival, deterministic service, single server).

- Arrival: Poisson process, dispatched by weighted load balancer
- Service time: `T_base * s_i(t)` where `s_i(t)` is the slowdown factor
- The M/D/1 model naturally produces nonlinear tail latency growth as utilization approaches 1.0, which approximates the "danger zone" effect

See DR-003 for rationale. May upgrade to M/G/1 or batch-aware model if M/D/1 proves insufficient.

## Fault Injection

Slowdown factor `s >= 1.0` applied multiplicatively to service time:

| Pattern | Model | Parameters |
|---------|-------|------------|
| Permanent | `s = const` after onset | `s`, `t_onset` |
| Fluctuating | Alternates `1.0` / `s_peak` | `s_peak`, `d_on`, `d_off` |
| Progressive | `s(t) = 1.0 + beta * (t - t_onset)` | `beta`, `t_onset` |
| Intermittent | Random flips between `1.0` / `s_peak` | `s_peak`, `p_flip` |

Severity score: `severity = 1 - 1/s` (continuous in [0, 1)).

## Calibration Sources

| Aspect | Source | Data |
|--------|--------|------|
| Slowdown distribution | Perseus (FAST'23) | 315 fail-slow drives, slowdown ratios |
| Danger zone thresholds | ADR (NSDI'25) | Cassandra: 0.1-3ms, etcd: 1-2ms |
| Thermal throttling curve | TAPAS (ASPLOS'25) | Piecewise polynomial, MAE < 1 deg C |
| Fault incidence rate | IASO (ATC'19) | 1.02% annual fail-slow rate |

## System Configuration

| Parameter | Value | Note |
|-----------|-------|------|
| Cluster size | 16 nodes | See DR-004; scale to 64 later |
| Per-node capacity | 100 req/s | Normalized |
| Request latency (healthy) | 20ms | Typical DNN inference |
| SLO | P99 <= 100ms | 5x base latency |
| Decision epoch | 500ms | Strategy selector interval |
| Load range | 50%-95% utilization | Vary across experiments |

## Components to Implement

1. **RequestGenerator** - Poisson arrival process
2. **LoadBalancer** - Weighted routing with dynamic weight updates
3. **WorkerNode** - M/D/1 queue with slowdown factor
4. **FaultInjector** - Configurable fault patterns per node
5. **Monitor** - Collects per-node and system-wide metrics per epoch
6. **Detector** - Computes severity scores via peer comparison
7. **StrategySelector** - Core algorithm (see framework design Section 3.3)
8. **SpeculationManager** - Hedged request dispatch and cancellation
9. **RecoveryProber** - Periodic probes to isolated nodes
10. **MetricsCollector** - Records all metrics for post-hoc analysis

## Experiment Parameters

All experiments use 16 nodes, 100 req/s per node, 10ms base service time, SLO P99 <= 100ms, 500ms decision epoch.

| Scenario | Fault Type | Load | Duration | Warmup | Nodes Affected |
|----------|-----------|------|----------|--------|----------------|
| S1: Severity Sweep | PermanentFault, s=1.0-10.0 | 90% | 60s | 10s | 1 |
| S2: Progressive | ProgressiveFault, beta=0.05, s_max=8.0 | 80% | 120s | 10s | 1 |
| S3: Flash Crowd | PermanentFault s=2.0 + variable load (70/95/70%) | 70-95% | 100s | 5s | 1 |
| S4: Multi-Node | PermanentFault, s~Uniform(1.5,3.0) | 80% | 60s | 5s | 4 (nodes 0-3) |
| S5: Fluctuating | FluctuatingFault, s_peak=3.0, 5s on/5s off | 80% | 120s | 10s | 1 |
| S6: Cascade | 2x PermanentFault, staggered onset | 85% | 90s | 5s | 2 |
| S7: Recovery | PermanentFault with finite duration | 80% | 100s | 5s | 1 |

Each scenario runs 5 baselines x 10 independent runs. See `docs/experiments-guide.md` for details.

The RequestGenerator supports a `load_schedule` parameter for time-varying arrival rates (used in S3).

## Open Questions

- [x] Is M/D/1's nonlinearity sufficient to reproduce ADR's danger zone? (validated in S6: 85% load + 2 faults -> P99 > 100ms)
- [ ] Batch processing in inference (dynamic batching in vLLM/Triton) - ignore for v1?
- [ ] Network latency between load balancer and workers - model or ignore?
