"""Metrics extraction from GPU simulation state."""

from __future__ import annotations

import jax
import jax.numpy as jnp
import numpy as np

from simulator_gpu.config import GPUConfig
from simulator_gpu.state import SimState


def histogram_percentile(histogram: jax.Array, percentile: float) -> jnp.float32:
    """Compute a percentile from a latency histogram.

    Args:
        histogram: int32[B] bin counts.
        percentile: Target percentile in [0, 100].

    Returns:
        Latency in steps at the given percentile.
    """
    cumsum = jnp.cumsum(histogram)
    total = cumsum[-1]
    threshold = total * (percentile / 100.0)
    # searchsorted: find first bin where cumsum >= threshold
    bin_idx = jnp.searchsorted(cumsum, threshold, side="left")
    return bin_idx.astype(jnp.float32)


def extract_results(state: SimState, gpu_config: GPUConfig) -> dict:
    """Extract final results from simulation state.

    Converts GPU arrays to Python scalars and computes percentiles
    from the latency histogram. Returns a dict compatible with the
    SimPy simulator's output format.

    Args:
        state: Final simulation state.
        gpu_config: GPU configuration (for dt conversion).

    Returns:
        Dict with keys matching simulator.run.run_simulation() output.
    """
    hist = state.histogram
    dt = gpu_config.dt
    total = int(state.total_completed)

    if total == 0:
        return {
            "total": 0, "avg_latency": 0, "p50_latency": 0,
            "p95_latency": 0, "p99_latency": 0, "p999_latency": 0,
            "max_latency": 0, "tail_ratio": 0, "throughput": 0,
            "goodput": 0, "slo_violation_rate": 0, "hedge_count": 0,
            "affected_ratio": 0,
        }

    p50_steps = float(histogram_percentile(hist, 50))
    p95_steps = float(histogram_percentile(hist, 95))
    p99_steps = float(histogram_percentile(hist, 99))
    p999_steps = float(histogram_percentile(hist, 99.9))

    # Convert steps to seconds
    p50 = p50_steps * dt
    p95 = p95_steps * dt
    p99 = p99_steps * dt
    p999 = p999_steps * dt

    # Average from histogram: sum(bin_center * count) / total
    hist_np = np.array(hist)
    bin_centers = (np.arange(len(hist_np)) + 0.5)  # in steps
    avg_steps = float(np.sum(bin_centers * hist_np) / total)
    avg = avg_steps * dt

    # Max: highest non-zero bin
    nonzero = np.nonzero(hist_np)[0]
    max_steps = float(nonzero[-1] + 1) if len(nonzero) > 0 else 0.0
    max_lat = max_steps * dt

    tail_ratio = p99 / p50 if p50 > 0 else 0.0

    return {
        "total": total,
        "avg_latency": avg,
        "p50_latency": p50,
        "p95_latency": p95,
        "p99_latency": p99,
        "p999_latency": p999,
        "max_latency": max_lat,
        "tail_ratio": tail_ratio,
        "throughput": 0.0,  # Filled by caller with duration info
        "goodput": 0.0,  # Filled by caller
        "slo_violation_rate": 0.0,  # Filled by caller
        "hedge_count": 0,
        "affected_ratio": 0.0,  # Filled by caller
    }


def compute_slo_metrics(
    histogram: jax.Array,
    slo_target_steps: int,
    total_completed: int,
    effective_duration: float,
) -> dict:
    """Compute SLO-related metrics from histogram.

    Args:
        histogram: int32[B] bin counts.
        slo_target_steps: SLO target in time steps.
        total_completed: Total completed requests.
        effective_duration: Duration minus warmup in seconds.

    Returns:
        Dict with throughput, goodput, slo_violation_rate.
    """
    hist_np = np.array(histogram)
    good = int(np.sum(hist_np[:slo_target_steps]))
    violations = total_completed - good

    return {
        "throughput": total_completed / effective_duration if effective_duration > 0 else 0,
        "goodput": good / effective_duration if effective_duration > 0 else 0,
        "slo_violation_rate": violations / total_completed if total_completed > 0 else 0,
    }
