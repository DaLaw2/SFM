"""Service processing kernel: advance workers by one time step."""

from __future__ import annotations

import jax
import jax.numpy as jnp

from simulator_gpu.kernels.queue import dequeue_entry, record_departure


def _sample_service_steps(
    key: jax.Array,
    t_base_steps: int,
    slowdown: jnp.float32,
    service_cv: float,
) -> jnp.int32:
    """Sample service time in steps.

    M/D/1 (cv=0): deterministic round(t_base * slowdown).
    M/G/1 (cv>0): Gamma(shape=1/cv^2, scale=mean*cv^2), then round.
    Uses round() not floor() to avoid systematic bias.
    """
    mean = t_base_steps * slowdown

    def deterministic(_):
        return jnp.round(mean).astype(jnp.int32)

    def stochastic(k):
        cv = jnp.maximum(service_cv, 1e-6)  # Guard against tracing with cv=0
        shape = 1.0 / (cv * cv)
        scale = mean * cv * cv
        sample = jax.random.gamma(k, shape) * scale
        return jnp.round(sample).astype(jnp.int32)

    steps = jax.lax.cond(service_cv <= 0.0, deterministic, stochastic, key)
    return jnp.maximum(steps, jnp.int32(1))


def advance_service(
    remaining_service: jax.Array,
    queue_lengths: jax.Array,
    slowdown_factors: jax.Array,
    entry_times: jax.Array,
    entry_head: jax.Array,
    last_departure_step: jax.Array,
    departure_intervals: jax.Array,
    departure_tail: jax.Array,
    histogram: jax.Array,
    total_completed: jnp.int32,
    current_step: jnp.int32,
    warmup_step: jnp.int32,
    service_key: jax.Array,
    t_base_steps: int,
    service_cv: float,
    n_workers: int,
    queue_buf_size: int,
    departure_buf_size: int,
    histogram_bins: int,
) -> tuple[
    jax.Array,  # remaining_service
    jax.Array,  # queue_lengths
    jax.Array,  # entry_times
    jax.Array,  # entry_head
    jax.Array,  # last_departure_step
    jax.Array,  # departure_intervals
    jax.Array,  # departure_tail
    jax.Array,  # histogram
    jnp.int32,  # total_completed
]:
    """Advance service for all workers by one time step.

    For each worker:
    1. If remaining > 0: decrement remaining by 1.
    2. If remaining just hit 0: complete the request — record latency,
       departure interval, advance entry_head, decrement queue.
    3. If idle and queue > 0: start next request (handles both
       just-completed and newly-arrived-to-idle-worker cases).

    Supports M/G/1 when service_cv > 0 via Gamma-distributed service times.
    """
    # Pre-split keys for all workers (only used if service starts)
    worker_keys = jax.random.split(service_key, n_workers)

    def process_worker(i, carry):
        (rem, ql, e_times, e_head, last_dep, dep_ints, dep_tail,
         hist, completed) = carry

        remaining_i = rem[i]
        queue_i = ql[i]
        slowdown_i = slowdown_factors[i]

        # --- Step 1: Decrement remaining service time ---
        was_busy = remaining_i > 0
        new_remaining = jnp.maximum(remaining_i - 1, 0)
        just_completed = was_busy & (new_remaining == 0)

        # --- Step 2: Handle completion ---
        entry_step, new_e_head_tmp = dequeue_entry(
            e_times, e_head, i, queue_buf_size,
        )
        latency_steps = current_step - entry_step

        # Record in histogram (filter by entry_step for warmup consistency)
        after_warmup = entry_step >= warmup_step
        record_latency = just_completed & after_warmup
        bin_idx = jnp.clip(latency_steps, 0, histogram_bins - 1)
        new_hist = jnp.where(
            record_latency,
            hist.at[bin_idx].add(1),
            hist,
        )

        # Record departure interval
        new_dep_ints, new_dep_tail_tmp, new_last_dep_tmp = record_departure(
            dep_ints, dep_tail, last_dep, i, current_step, departure_buf_size,
        )
        final_dep_ints = jnp.where(just_completed, new_dep_ints, dep_ints)
        final_dep_tail = jnp.where(just_completed, new_dep_tail_tmp, dep_tail)
        final_last_dep = jnp.where(just_completed, new_last_dep_tmp, last_dep)

        final_e_head = jnp.where(just_completed, new_e_head_tmp, e_head)

        new_completed = completed + jnp.where(
            just_completed & after_warmup, 1, 0
        )

        new_queue_i = jnp.where(just_completed, jnp.maximum(queue_i - 1, 0), queue_i)
        new_ql = ql.at[i].set(new_queue_i)

        # --- Step 3: Start next request if idle and queue non-empty ---
        should_start = (new_remaining == 0) & (new_queue_i > 0)
        svc_steps = _sample_service_steps(
            worker_keys[i], t_base_steps, slowdown_i, service_cv,
        )
        final_remaining = jnp.where(should_start, svc_steps, new_remaining)

        new_rem = rem.at[i].set(final_remaining)

        return (new_rem, new_ql, e_times, final_e_head, final_last_dep,
                final_dep_ints, final_dep_tail, new_hist, new_completed)

    init = (remaining_service, queue_lengths, entry_times, entry_head,
            last_departure_step, departure_intervals, departure_tail,
            histogram, total_completed)

    return jax.lax.fori_loop(0, n_workers, process_worker, init)
