"""JAX GPU simulator entry point."""

from __future__ import annotations

import jax
import jax.numpy as jnp
import numpy as np

from simulator.config import SimConfig, FaultConfig, StrategyConfig
from simulator_gpu.config import GPUConfig
from simulator_gpu.state import SimState, init_state
from simulator_gpu.kernels.arrivals import sample_arrivals
from simulator_gpu.kernels.routing import route_arrivals
from simulator_gpu.kernels.service import advance_service
from simulator_gpu.kernels.fault import precompute_slowdown_schedule
from simulator_gpu.metrics import extract_results, compute_slo_metrics


def _make_step_fn(
    n_workers: int,
    arrival_rate: float,
    dt: float,
    t_base_steps: int,
    service_cv: float,
    max_arrivals: int,
    queue_buf_size: int,
    departure_buf_size: int,
    histogram_bins: int,
):
    """Create a single-step function with static config baked in.

    Not decorated with @jax.jit here — the epoch function wraps this
    in lax.scan which handles tracing. Nested JIT would prevent XLA
    from optimizing the full scan loop.
    """

    def sim_step(state: SimState, slowdown_row: jax.Array) -> SimState:
        """Advance simulation by one time step."""
        # Split PRNG: arrivals, routing, service (for M/G/1), next state
        key, k_arrive, k_route, k_service = jax.random.split(state.rng_key, 4)

        # Update slowdown factors
        new_slowdown = slowdown_row

        # Sample arrivals (masked to 0 beyond total_steps for remainder padding)
        within_duration = state.step < state.total_steps
        n_arrivals_raw = sample_arrivals(k_arrive, arrival_rate, dt, max_arrivals)
        n_arrivals = jnp.where(within_duration, n_arrivals_raw, jnp.int32(0))

        # Route arrivals (sequential within step to avoid herd effect)
        new_depths, new_entry_times, new_entry_tail, n_routed = route_arrivals(
            key=k_route,
            n_arrivals=n_arrivals,
            weights=state.weights,
            queue_depths=state.queue_lengths,
            excluded=state.excluded,
            entry_times=state.entry_times,
            entry_tail=state.entry_tail,
            current_step=state.step,
            n_workers=n_workers,
            queue_buf_size=queue_buf_size,
            max_arrivals=max_arrivals,
        )

        # Advance service: completions + start idle workers with new arrivals
        (
            new_remaining, new_depths, new_entry_times_2, new_entry_head,
            new_last_dep, new_dep_ints, new_dep_tail,
            new_hist, new_completed,
        ) = advance_service(
            remaining_service=state.remaining_service,
            queue_lengths=new_depths,
            slowdown_factors=new_slowdown,
            entry_times=new_entry_times,
            entry_head=state.entry_head,
            last_departure_step=state.last_departure_step,
            departure_intervals=state.departure_intervals,
            departure_tail=state.departure_tail,
            histogram=state.histogram,
            total_completed=state.total_completed,
            current_step=state.step,
            warmup_step=state.warmup_step,
            service_key=k_service,
            t_base_steps=t_base_steps,
            service_cv=service_cv,
            n_workers=n_workers,
            queue_buf_size=queue_buf_size,
            departure_buf_size=departure_buf_size,
            histogram_bins=histogram_bins,
        )

        return SimState(
            step=state.step + 1,
            rng_key=key,
            queue_lengths=new_depths,
            remaining_service=new_remaining,
            slowdown_factors=new_slowdown,
            weights=state.weights,
            excluded=state.excluded,
            entry_times=new_entry_times,
            entry_head=new_entry_head,
            entry_tail=new_entry_tail,
            last_departure_step=new_last_dep,
            departure_intervals=new_dep_ints,
            departure_head=state.departure_head,
            departure_tail=new_dep_tail,
            histogram=new_hist,
            total_completed=new_completed,
            total_arrived=state.total_arrived + n_routed,
            warmup_step=state.warmup_step,
            total_steps=state.total_steps,
        )

    return sim_step


def _make_epoch_fn(step_fn, epoch_steps: int):
    """Create a function that runs one epoch (many steps) via lax.scan."""

    def run_epoch(state: SimState, slowdown_chunk: jax.Array) -> SimState:
        """Run one epoch of simulation.

        Args:
            state: Current state.
            slowdown_chunk: float32[epoch_steps, N] slowdown schedule.

        Returns:
            State after the epoch.
        """
        def scan_body(st, sd_row):
            new_st = step_fn(st, sd_row)
            return new_st, None

        final_state, _ = jax.lax.scan(scan_body, state, slowdown_chunk)
        return final_state

    return run_epoch


def run_simulation_gpu(
    config: SimConfig | None = None,
    fault_config: FaultConfig | None = None,
    strategy_config: StrategyConfig | None = None,
    gpu_config: GPUConfig | None = None,
    enable_mitigation: bool = False,
    verbose: bool = True,
) -> dict:
    """Run a single simulation on GPU.

    When enable_mitigation=True, runs the CPU-side control plane
    (Detector → Selector → AIMD) after each epoch, updating GPU
    state with new weights and exclusion masks.

    Args:
        config: Simulation configuration.
        fault_config: Fault injection configuration.
        strategy_config: Strategy configuration.
        gpu_config: GPU-specific configuration.
        enable_mitigation: Whether to enable the control plane.
        verbose: Print progress info.

    Returns:
        Dict with same keys as simulator.run.run_simulation().
    """
    if config is None:
        config = SimConfig()
    if fault_config is None:
        fault_config = FaultConfig()
    if gpu_config is None:
        gpu_config = GPUConfig()

    N = config.n_workers
    total_steps = gpu_config.seconds_to_steps(config.duration)
    t_base_steps = round(config.t_base / gpu_config.dt)
    epoch_steps = gpu_config.epoch_steps

    if verbose:
        mit_str = "mitigation ON" if enable_mitigation else "no mitigation"
        print(f"GPU Sim: {total_steps} steps, dt={gpu_config.dt*1000:.1f}ms, "
              f"t_base={t_base_steps} steps, N={N}, {mit_str}")

    # Pre-compute slowdown schedule on CPU
    schedule_np = precompute_slowdown_schedule(config, fault_config, gpu_config)

    # Pad schedule to multiple of epoch_steps
    n_epochs_ceil = (total_steps + epoch_steps - 1) // epoch_steps
    padded_steps = n_epochs_ceil * epoch_steps
    if padded_steps > total_steps:
        pad_rows = padded_steps - total_steps
        schedule_np = np.pad(
            schedule_np, ((0, pad_rows), (0, 0)), constant_values=1.0,
        )
    schedule = jnp.array(schedule_np)

    # Initialize state
    rng_key = jax.random.PRNGKey(config.seed)
    state = init_state(config, gpu_config, rng_key)

    # Build step and epoch functions
    step_fn = _make_step_fn(
        n_workers=N,
        arrival_rate=config.arrival_rate,
        dt=gpu_config.dt,
        t_base_steps=t_base_steps,
        service_cv=config.service_cv,
        max_arrivals=gpu_config.max_arrivals_per_step,
        queue_buf_size=gpu_config.queue_buf_size,
        departure_buf_size=gpu_config.departure_buf_size,
        histogram_bins=gpu_config.histogram_bins,
    )
    epoch_fn = _make_epoch_fn(step_fn, epoch_steps)
    epoch_fn_jit = jax.jit(epoch_fn)

    # Control plane (CPU side)
    bridge = None
    if enable_mitigation:
        from simulator_gpu.control.bridge import ControlBridge
        bridge = ControlBridge(config, gpu_config, strategy_config)

    if verbose:
        print(f"Running {n_epochs_ceil} epochs of {epoch_steps} steps each...")

    for epoch_idx in range(n_epochs_ceil):
        start = epoch_idx * epoch_steps
        end = start + epoch_steps
        chunk = schedule[start:end]
        state = epoch_fn_jit(state, chunk)

        # Control plane update after each epoch
        if bridge is not None:
            # Block to ensure epoch data is ready
            jax.block_until_ready(state.departure_intervals)
            new_weights, new_excluded = bridge.step(state)
            state = state._replace(weights=new_weights, excluded=new_excluded)

        if verbose and (epoch_idx + 1) % 20 == 0:
            print(f"  Epoch {epoch_idx + 1}/{n_epochs_ceil}")

    # Block until computation completes
    jax.block_until_ready(state.histogram)

    # Extract results
    result = extract_results(state, gpu_config)

    # Compute throughput/SLO metrics
    effective_duration = config.duration - config.warmup
    slo_target_steps = round(config.slo_target / gpu_config.dt)
    slo_metrics = compute_slo_metrics(
        state.histogram, slo_target_steps, result["total"], effective_duration,
    )
    result.update(slo_metrics)

    # Affected ratio
    fault_node_ids = set()
    for scenario in fault_config.scenarios:
        fault_node_ids.update(scenario.node_indices)
    result["affected_ratio"] = len(fault_node_ids) / N if fault_node_ids else 0.0

    if verbose:
        print(f"GPU Sim complete: {config.duration}s ({config.warmup}s warmup)")
        print(f"Total requests: {result['total']}")
        print(f"Avg latency:  {result['avg_latency'] * 1000:.1f}ms")
        print(f"P99 latency:  {result['p99_latency'] * 1000:.1f}ms")
        print(f"Throughput:   {result['throughput']:.0f} req/s")

    return result


def run_batch_gpu(
    configs: list[tuple[SimConfig, FaultConfig]],
    gpu_config: GPUConfig | None = None,
    verbose: bool = True,
) -> list[dict]:
    """Run multiple simulations in a batch using vmap.

    All simulations must share the same structural parameters (n_workers,
    duration, load_factor, t_base) but can differ in seed and fault config.

    Args:
        configs: List of (SimConfig, FaultConfig) pairs.
        gpu_config: GPU-specific configuration.
        verbose: Print progress info.

    Returns:
        List of result dicts, one per simulation.
    """
    if not configs:
        return []
    if gpu_config is None:
        gpu_config = GPUConfig()

    # Validate all configs share structural parameters
    base = configs[0][0]
    for sim_cfg, _ in configs[1:]:
        assert sim_cfg.n_workers == base.n_workers, "All configs must share n_workers"
        assert sim_cfg.duration == base.duration, "All configs must share duration"
        assert sim_cfg.t_base == base.t_base, "All configs must share t_base"
        assert sim_cfg.load_factor == base.load_factor, "All configs must share load_factor"
        assert sim_cfg.service_cv == base.service_cv, "All configs must share service_cv"

    batch_size = len(configs)
    N = base.n_workers
    total_steps = gpu_config.seconds_to_steps(base.duration)
    t_base_steps = round(base.t_base / gpu_config.dt)
    epoch_steps = gpu_config.epoch_steps

    if verbose:
        print(f"GPU Batch: {batch_size} sims, {total_steps} steps each")

    # Pre-compute all slowdown schedules (CPU), padded to epoch boundary
    n_epochs_ceil = (total_steps + epoch_steps - 1) // epoch_steps
    padded_steps = n_epochs_ceil * epoch_steps

    schedules_list = []
    for sim_cfg, fault_cfg in configs:
        sched = precompute_slowdown_schedule(sim_cfg, fault_cfg, gpu_config)
        if padded_steps > total_steps:
            sched = np.pad(
                sched, ((0, padded_steps - total_steps), (0, 0)),
                constant_values=1.0,
            )
        schedules_list.append(sched)
    schedules = np.stack(schedules_list)  # [B, T_padded, N]
    schedules_jax = jnp.array(schedules)

    # Initialize batch of states
    keys = jnp.stack([
        jax.random.PRNGKey(sim_cfg.seed)
        for sim_cfg, _ in configs
    ])
    batch_init = jax.vmap(lambda k: init_state(base, gpu_config, k))
    states = batch_init(keys)

    # Build step and epoch functions
    step_fn = _make_step_fn(
        n_workers=N,
        arrival_rate=base.arrival_rate,
        dt=gpu_config.dt,
        t_base_steps=t_base_steps,
        service_cv=base.service_cv,
        max_arrivals=gpu_config.max_arrivals_per_step,
        queue_buf_size=gpu_config.queue_buf_size,
        departure_buf_size=gpu_config.departure_buf_size,
        histogram_bins=gpu_config.histogram_bins,
    )
    epoch_fn = _make_epoch_fn(step_fn, epoch_steps)
    batch_epoch = jax.jit(jax.vmap(epoch_fn))

    if verbose:
        print(f"Running {n_epochs_ceil} epochs...")

    for epoch_idx in range(n_epochs_ceil):
        start = epoch_idx * epoch_steps
        end = start + epoch_steps
        chunks = schedules_jax[:, start:end, :]  # [B, epoch_steps, N]
        states = batch_epoch(states, chunks)

        if verbose and (epoch_idx + 1) % 20 == 0:
            print(f"  Epoch {epoch_idx + 1}/{n_epochs_ceil}")

    jax.block_until_ready(states.histogram)

    # Extract results for each sim
    results = []
    effective_duration = base.duration - base.warmup
    slo_target_steps = round(base.slo_target / gpu_config.dt)

    for i in range(batch_size):
        state_i = jax.tree.map(lambda x: x[i], states)
        result = extract_results(state_i, gpu_config)

        slo_metrics = compute_slo_metrics(
            state_i.histogram, slo_target_steps, result["total"], effective_duration,
        )
        result.update(slo_metrics)

        _, fault_cfg = configs[i]
        fault_node_ids = set()
        for scenario in fault_cfg.scenarios:
            fault_node_ids.update(scenario.node_indices)
        result["affected_ratio"] = len(fault_node_ids) / N if fault_node_ids else 0.0

        results.append(result)

    if verbose:
        print(f"Batch complete: {batch_size} sims")

    return results
