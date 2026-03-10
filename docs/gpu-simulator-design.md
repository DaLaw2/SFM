# V19: JAX GPU Simulator Design

**Date:** 2026-03-08
**Context:** Three experts (GPU/JAX, queueing theory, systems architect) independently analyzed the GPU simulator design. This document synthesizes their findings.

## Hardware

- 3× Nvidia A2 (1280 CUDA cores, 16GB VRAM) — school internal network, Linux
- 1× GTX 1660 (1408 CUDA cores, 6GB VRAM) — local dev, Windows (need WSL2 for JAX CUDA)

## Architecture Summary

### Core Approach: Time-Stepped + vmap Batch

- **Not** event-driven on GPU. SimPy's coroutine model cannot be vectorized.
- Fixed time step `dt`: process arrivals → route (P2C) → advance service → update metrics
- `jax.vmap` over independent simulation instances (the **main** source of speedup)
- `jax.pmap` across GPUs (A2s separate from 1660 due to different compute capability)
- Control plane runs on CPU host every 500ms (only 120 calls per 60s sim)

### Package Structure

```
simulator/              # Existing SimPy (untouched)
  config.py             # SimConfig, FaultConfig, StrategyConfig (shared)
simulator_gpu/          # New JAX simulator
  __init__.py
  run.py                # run_simulation_gpu() entry point
  state.py              # JAX pytree state (NamedTuples)
  kernels/
    arrivals.py         # Poisson(λ·dt) sampling
    routing.py          # P2C via Gumbel-max trick
    service.py          # M/D/1 and M/G/1
    queue.py            # FIFO scan per worker
    fault.py            # Pre-computed slowdown schedule
  control/              # Phase 2
    detector.py
    selector.py
    aimd.py
tests/
  test_gpu_validation.py  # SimPy vs GPU cross-validation
```

## Critical Design Decisions

### 1. Time Step: dt = 0.1ms (configurable)

**From queueing theory expert:**
- M/D/1 with t_base=10ms: service = 100 steps, **zero discretization error**
- P99 direct error ≤ 0.1ms (≤ 0.2% of 50ms SLO)
- Indirect error from queue dynamics: ~0.2-0.5ms with mitigation

**Trade-off:** dt=0.5ms reduces steps 5× (120K vs 600K) with slightly more error. Start with 0.1ms, tune later if compilation too slow.

### 2. Arrivals: Poisson(λ·dt), NOT Bernoulli

**Critical finding from queueing theory expert:**
- λ·dt = 2560 × 0.0001 = 0.256
- Bernoulli loses 2.77% of multi-arrivals → **underestimates tail latency**
- Must use `jax.random.poisson(key, rate * dt)` per step
- Cap at MAX_ARRIVALS_PER_STEP = 8 (P(≥8) ≈ 0)

### 3. Intra-Step Sequential P2C

**Problem:** Multiple arrivals in same step see identical queue depths → herd effect.
**Solution:** Process arrivals sequentially within each step via `jax.lax.scan`:

```python
def route_one(carry, key_i):
    queue_depths, idx = carry
    worker = p2c_select(key_i, weights, queue_depths)
    should_route = idx < n_arrivals
    new_depths = jnp.where(should_route,
        queue_depths + jax.nn.one_hot(worker, N, dtype=jnp.int32), queue_depths)
    return (new_depths, idx + 1), worker
```

### 4. Latency Tracking: Fixed-Bin Histogram

- Range [0, 500ms], 5000 bins, bin width 0.1ms
- 20KB per instance (vs 600KB for storing all 150K latencies)
- Percentiles via `jnp.searchsorted(cumsum, threshold)`
- 10,000 instances = 200MB total — trivial

### 5. Queue State: Circular Buffer for Entry Times

- Per worker: circular buffer of arrival step indices, size 64
- Enables exact latency = (completion_step - entry_step) × dt
- Memory: 32 workers × 64 × 4B = 8KB/instance

### 6. Service Time Rounding

- M/D/1: zero error when dt divides t_base (10ms / 0.1ms = 100 steps exact)
- M/G/1: use `round()` not `floor()` to avoid systematic bias
- Stochastic rounding for maximum accuracy

## Memory Budget

| Component | Per Instance | 10K Instances |
|---|---|---|
| Worker state (5 arrays × 32) | 640B | 6.4MB |
| Latency histogram (5000 bins) | 20KB | 200MB |
| Queue entry buffer (32×64) | 8KB | 80MB |
| Departure interval buffer (32×50) | 6.4KB | 64MB |
| Control state | ~2KB | 20MB |
| **Total** | **~37KB** | **~370MB** |

A2 (16GB): can fit ~400K instances. Memory is NOT the bottleneck.

## Performance Estimates

**GPU/JAX expert estimate (XLA fusion):**
- 1000 instances × 600K steps: ~1-3 seconds on A2
- S1 experiment (550 jobs): **< 10 seconds** (single A2)
- Large sweep (10K jobs): **< 30 seconds** (3× A2 via pmap)

**vs current SimPy:**
- S1 (550 jobs) on weak CPU: ~10-15 minutes
- Expected speedup: **60-100×**

## Validation Methodology

**From queueing theory expert:**

1. Run 50 paired simulations (same 50 seeds, both backends)
2. Compare P50/P95/P99 with bootstrap 95% CI on paired differences
3. KS test on full latency distributions
4. Tolerance: P99 relative error < 2%, absolute < 0.2ms

**Phased validation:**
- Phase 1: Single worker M/D/1 vs theory (E[W] = ρd / 2(1-ρ))
- Phase 2: 32 workers + P2C, no fault → compare with SimPy
- Phase 3: Permanent fault + no_mitigation → compare severity sweep
- Phase 4: Full control loop → compare epoch-level traces

## Implementation Phases

### Phase 1: Core Engine (3-5 days)
- M/D/1 + P2C + permanent fault + no_mitigation
- Validate against SimPy on 4 test cases
- **Milestone:** P99 within 2% of SimPy on healthy + permanent_2x

### Phase 2: Precise Latency Tracking (2-3 days)
- Circular buffer entry times
- Histogram-based percentile computation
- **Milestone:** P50/P95/P99/P999 all within tolerance

### Phase 3: Fault Injection (1 day)
- Pre-compute slowdown schedule on CPU, pass as static array
- PermanentFault, ProgressiveFault patterns
- **Milestone:** Severity sweep matches SimPy

### Phase 4: Control Plane (3-5 days)
- Detector (departure interval P10 from buffer)
- Selector (strategy selection with G2 isolation budget)
- AIMD weight updates
- Runs on CPU host, updates GPU state every 500ms
- **Milestone:** adaptive and fixed_isolation match SimPy

### Phase 5: M/G/1 + Advanced (1-2 days)
- Gamma-distributed service times (`jax.random.gamma`)
- IntermittentFault, FluctuatingFault patterns
- **Milestone:** S1-S7 all validated

### Phase 6: Experiment Integration (2 days)
- runner_gpu.py with same interface as runner.py
- Multi-GPU via pmap (A2 cluster) or separate processes
- **Milestone:** Full S1 experiment runs on GPU

**Total: ~2-3 weeks**

## Key Risks

| Risk | Severity | Mitigation |
|---|---|---|
| JAX on Windows needs WSL2 | Medium | Dev in WSL2, deploy to Linux A2s |
| XLA compilation time (>5 min first run) | Medium | Cache compiled functions; use AOT |
| Hedging semantics hard in time-step model | High | Skip hedging in Phase 1-4; use SimPy for lit_hedged baseline |
| Control loop stateful logic hard to vectorize | Medium | Keep control on CPU host, only queueing on GPU |
| A2s on different machines can't share pmap | Medium | Data parallelism: each machine runs subset, merge CSV |
| Queue buffer overflow at extreme load | Low | QUEUE_BUF_SIZE=64, clip as guard |

## Expert Consensus

All three experts agree:
1. **vmap batch is the real speedup** — not parallelizing within a single sim
2. **Control plane on CPU** — too complex and infrequent to justify GPU
3. **Poisson arrivals, not Bernoulli** — critical for tail latency accuracy
4. **JAX is the right framework** — vmap + lax.scan + pmap is unmatched
5. **Skip hedging initially** — most complex feature, least important for current research
6. **dt=0.1ms is safe** — zero error for M/D/1, <0.5ms error overall
