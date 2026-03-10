"""P2C routing with Gumbel-max trick for weighted sampling."""

from __future__ import annotations

import jax
import jax.numpy as jnp


def _gumbel_sample_two(key: jax.Array, log_weights: jax.Array) -> tuple[jnp.int32, jnp.int32]:
    """Sample two distinct indices using Gumbel-max trick.

    Gumbel-max: argmax(log_w + Gumbel(0,1)) is equivalent to
    categorical sampling with weights proportional to exp(log_w).

    For two samples without replacement: take top-2 of the perturbed scores.
    """
    k1, k2 = jax.random.split(key)
    gumbel_noise = jax.random.gumbel(k1, shape=log_weights.shape)
    perturbed = log_weights + gumbel_noise

    # First sample: argmax
    idx1 = jnp.argmax(perturbed)

    # Second sample: mask out first, take argmax again
    perturbed_masked = perturbed.at[idx1].set(-jnp.inf)
    idx2 = jnp.argmax(perturbed_masked)

    return idx1.astype(jnp.int32), idx2.astype(jnp.int32)


def p2c_select(
    key: jax.Array,
    weights: jax.Array,
    queue_depths: jax.Array,
    excluded: jax.Array,
) -> jnp.int32:
    """Select a worker using Power-of-Two-Choices.

    1. Compute effective weights (excluded workers get weight 0).
    2. Sample 2 candidates via Gumbel-max weighted sampling.
    3. Return the candidate with shorter queue.

    Args:
        key: JAX PRNG key.
        weights: float32[N] routing weights.
        queue_depths: int32[N] current queue depths.
        excluded: bool[N] exclusion flags.

    Returns:
        Selected worker index as int32 scalar.
    """
    # Fallback: if all workers are excluded, treat as none excluded
    all_excluded = jnp.all(excluded)
    effective_excluded = jnp.where(all_excluded, jnp.zeros_like(excluded), excluded)

    # Effective weights: excluded workers get -inf in log space
    effective = jnp.where(effective_excluded, 0.0, weights)
    effective = jnp.maximum(effective, 1e-10)  # Avoid log(0)
    log_w = jnp.log(effective)
    log_w = jnp.where(effective_excluded, -jnp.inf, log_w)

    idx1, idx2 = _gumbel_sample_two(key, log_w)

    # P2C: pick the one with shorter queue
    q1 = queue_depths[idx1]
    q2 = queue_depths[idx2]
    return jnp.where(q1 <= q2, idx1, idx2)


def route_arrivals(
    key: jax.Array,
    n_arrivals: jnp.int32,
    weights: jax.Array,
    queue_depths: jax.Array,
    excluded: jax.Array,
    entry_times: jax.Array,
    entry_tail: jax.Array,
    current_step: jnp.int32,
    n_workers: int,
    queue_buf_size: int,
    max_arrivals: int,
) -> tuple[jax.Array, jax.Array, jax.Array, jnp.int32]:
    """Route multiple arrivals sequentially within one time step.

    Uses jax.lax.scan to process arrivals one at a time, updating
    queue depths after each routing decision. This prevents the herd
    effect where multiple arrivals see identical queue depths and all
    route to the same worker.

    Args:
        key: JAX PRNG key.
        n_arrivals: Number of arrivals this step.
        weights: float32[N] routing weights.
        queue_depths: int32[N] current queue depths.
        excluded: bool[N] exclusion flags.
        entry_times: int32[N, Q] circular buffer of entry steps.
        entry_tail: int32[N] write pointers.
        current_step: Current simulation step.
        n_workers: Number of workers (N).
        queue_buf_size: Queue buffer size (Q).
        max_arrivals: Maximum arrivals per step (for scan length).

    Returns:
        (new_queue_depths, new_entry_times, new_entry_tail, total_routed)
    """
    keys = jax.random.split(key, max_arrivals)

    def route_one(carry, key_i):
        depths, e_times, e_tail, idx, arrived = carry

        worker = p2c_select(key_i, weights, depths, excluded)

        # Only route if idx < n_arrivals
        should_route = idx < n_arrivals

        # Update queue depth
        one_hot = jax.nn.one_hot(worker, n_workers, dtype=jnp.int32)
        new_depths = jnp.where(should_route, depths + one_hot, depths)

        # Record entry time in circular buffer
        buf_pos = e_tail[worker] % queue_buf_size
        new_e_times = jnp.where(
            should_route,
            e_times.at[worker, buf_pos].set(current_step),
            e_times,
        )
        new_e_tail = jnp.where(
            should_route,
            e_tail.at[worker].set(e_tail[worker] + 1),
            e_tail,
        )
        new_arrived = arrived + jnp.where(should_route, 1, 0)

        return (new_depths, new_e_times, new_e_tail, idx + 1, new_arrived), None

    init_carry = (queue_depths, entry_times, entry_tail, jnp.int32(0), jnp.int32(0))
    (new_depths, new_e_times, new_e_tail, _, total_routed), _ = jax.lax.scan(
        route_one, init_carry, keys,
    )

    return new_depths, new_e_times, new_e_tail, total_routed
