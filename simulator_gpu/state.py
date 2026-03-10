"""JAX simulation state as a NamedTuple pytree."""

from __future__ import annotations

from typing import NamedTuple

import jax.numpy as jnp
import jax

from simulator.config import SimConfig
from simulator_gpu.config import GPUConfig


class SimState(NamedTuple):
    """Complete state of one simulation instance.

    All arrays are JAX arrays. This is a valid pytree so it works
    with jax.vmap, jax.lax.scan, and jax.jit transparently.
    """

    # Time tracking
    step: jnp.int32  # Current time step

    # PRNG
    rng_key: jax.Array  # PRNGKey

    # Worker state (N = n_workers)
    queue_lengths: jax.Array  # int32[N] — requests waiting + in service
    remaining_service: jax.Array  # int32[N] — steps left for current request (0=idle)
    slowdown_factors: jax.Array  # float32[N] — current slowdown per worker

    # Routing state
    weights: jax.Array  # float32[N] — P2C routing weights
    excluded: jax.Array  # bool[N] — worker exclusion flags

    # Queue entry time tracking (circular buffer per worker)
    entry_times: jax.Array  # int32[N, Q] — arrival step of queued requests
    entry_head: jax.Array  # int32[N] — read pointer
    entry_tail: jax.Array  # int32[N] — write pointer

    # Departure interval tracking (circular buffer per worker)
    last_departure_step: jax.Array  # int32[N] — step of last departure per worker
    departure_intervals: jax.Array  # int32[N, D] — recent departure intervals
    departure_head: jax.Array  # int32[N] — read pointer
    departure_tail: jax.Array  # int32[N] — write pointer

    # Latency histogram (global)
    histogram: jax.Array  # int32[B] — latency bin counts

    # Counters
    total_completed: jnp.int32
    total_arrived: jnp.int32
    warmup_step: jnp.int32  # Steps before this are excluded from metrics
    total_steps: jnp.int32  # Total simulation steps (arrivals masked beyond this)


def init_state(
    sim_config: SimConfig,
    gpu_config: GPUConfig,
    rng_key: jax.Array,
) -> SimState:
    """Create initial simulation state from configs."""
    N = sim_config.n_workers
    Q = gpu_config.queue_buf_size
    D = gpu_config.departure_buf_size
    B = gpu_config.histogram_bins

    return SimState(
        step=jnp.int32(0),
        rng_key=rng_key,
        queue_lengths=jnp.zeros(N, dtype=jnp.int32),
        remaining_service=jnp.zeros(N, dtype=jnp.int32),
        slowdown_factors=jnp.ones(N, dtype=jnp.float32),
        weights=jnp.ones(N, dtype=jnp.float32),
        excluded=jnp.zeros(N, dtype=jnp.bool_),
        entry_times=jnp.zeros((N, Q), dtype=jnp.int32),
        entry_head=jnp.zeros(N, dtype=jnp.int32),
        entry_tail=jnp.zeros(N, dtype=jnp.int32),
        last_departure_step=jnp.full(N, -1, dtype=jnp.int32),
        departure_intervals=jnp.zeros((N, D), dtype=jnp.int32),
        departure_head=jnp.zeros(N, dtype=jnp.int32),
        departure_tail=jnp.zeros(N, dtype=jnp.int32),
        histogram=jnp.zeros(B, dtype=jnp.int32),
        total_completed=jnp.int32(0),
        total_arrived=jnp.int32(0),
        warmup_step=jnp.int32(gpu_config.seconds_to_steps(sim_config.warmup)),
        total_steps=jnp.int32(gpu_config.seconds_to_steps(sim_config.duration)),
    )
