"""Poisson arrival sampling for time-stepped simulation."""

from __future__ import annotations

import jax
import jax.numpy as jnp


def sample_arrivals(key: jax.Array, rate: float, dt: float, max_arrivals: int = 8) -> jnp.int32:
    """Sample number of arrivals in one time step from Poisson(rate * dt).

    Uses jax.random.poisson, NOT Bernoulli approximation.
    At rate=2560 req/s and dt=0.1ms, lambda*dt=0.256.
    Bernoulli would lose 2.77% of multi-arrival events, causing
    systematic underestimation of tail latency.

    Args:
        key: JAX PRNG key.
        rate: Arrival rate in requests per second.
        dt: Time step in seconds.
        max_arrivals: Cap to prevent extreme outliers (P(>=8) ≈ 0).

    Returns:
        Number of arrivals as int32 scalar.
    """
    n = jax.random.poisson(key, rate * dt)
    return jnp.minimum(n, max_arrivals).astype(jnp.int32)
