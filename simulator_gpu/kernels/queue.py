"""Circular buffer operations for queue entry times and departure intervals."""

from __future__ import annotations

import jax
import jax.numpy as jnp


def dequeue_entry(
    entry_times: jax.Array,
    entry_head: jax.Array,
    worker_id: jnp.int32,
    queue_buf_size: int,
) -> tuple[jnp.int32, jax.Array]:
    """Dequeue the oldest entry time from a worker's circular buffer.

    Args:
        entry_times: int32[N, Q] circular buffer.
        entry_head: int32[N] read pointers.
        worker_id: Which worker to dequeue from.
        queue_buf_size: Buffer size Q.

    Returns:
        (entry_step, new_entry_head)
    """
    pos = entry_head[worker_id] % queue_buf_size
    entry_step = entry_times[worker_id, pos]
    new_head = entry_head.at[worker_id].set(entry_head[worker_id] + 1)
    return entry_step, new_head


def record_departure(
    departure_intervals: jax.Array,
    departure_tail: jax.Array,
    last_departure_step: jax.Array,
    worker_id: jnp.int32,
    current_step: jnp.int32,
    departure_buf_size: int,
) -> tuple[jax.Array, jax.Array, jax.Array]:
    """Record a departure interval for a worker.

    Computes interval = current_step - last_departure_step, writes to
    the circular buffer, and updates last_departure_step.

    Args:
        departure_intervals: int32[N, D] circular buffer.
        departure_tail: int32[N] write pointers.
        last_departure_step: int32[N] step of last departure per worker.
        worker_id: Which worker departed.
        current_step: Current simulation step.
        departure_buf_size: Buffer size D.

    Returns:
        (new_departure_intervals, new_departure_tail, new_last_departure_step)
    """
    prev_step = last_departure_step[worker_id]
    has_prev = prev_step >= 0
    interval = current_step - prev_step

    # Write interval to buffer (only if we have a previous departure)
    buf_pos = departure_tail[worker_id] % departure_buf_size
    new_intervals = jnp.where(
        has_prev,
        departure_intervals.at[worker_id, buf_pos].set(interval),
        departure_intervals,
    )
    new_tail = jnp.where(
        has_prev,
        departure_tail.at[worker_id].set(departure_tail[worker_id] + 1),
        departure_tail,
    )

    # Always update last departure step
    new_last = last_departure_step.at[worker_id].set(current_step)

    return new_intervals, new_tail, new_last
