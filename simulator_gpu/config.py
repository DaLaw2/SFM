"""GPU simulator constants and configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GPUConfig:
    """GPU-specific simulation parameters.

    These control the time-stepping discretization and buffer sizes.
    The simulation-level parameters (n_workers, load_factor, etc.) come
    from simulator.config.SimConfig which is shared with the SimPy backend.
    """

    dt: float = 0.0001  # 0.1ms time step
    max_arrivals_per_step: int = 8  # Cap on Poisson arrivals per step
    queue_buf_size: int = 256  # Circular buffer slots per worker (must exceed max queue depth)
    histogram_bins: int = 5000  # Latency histogram bins (5000 * 0.1ms = 500ms max)
    departure_buf_size: int = 128  # Departure interval buffer per worker
    epoch_steps: int = 5000  # Steps per control epoch (500ms / 0.1ms)

    @property
    def histogram_max_ms(self) -> float:
        """Maximum latency tracked by histogram in milliseconds."""
        return self.histogram_bins * self.dt * 1000

    def seconds_to_steps(self, seconds: float) -> int:
        """Convert simulation seconds to time steps."""
        return round(seconds / self.dt)

    def steps_to_seconds(self, steps: int) -> float:
        """Convert time steps to simulation seconds."""
        return steps * self.dt
