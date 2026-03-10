"""Pre-compute fault slowdown schedules on CPU for GPU consumption."""

from __future__ import annotations

import numpy as np

from simulator.config import SimConfig, FaultConfig
from simulator_gpu.config import GPUConfig


def precompute_slowdown_schedule(
    sim_config: SimConfig,
    fault_config: FaultConfig,
    gpu_config: GPUConfig,
) -> np.ndarray:
    """Pre-compute the slowdown factor for every (step, worker) pair.

    This runs on CPU using numpy. The result is transferred to GPU as a
    static array, so the GPU kernel just does a table lookup each step.

    Args:
        sim_config: Simulation configuration.
        fault_config: Fault injection configuration.
        gpu_config: GPU configuration (for dt and total steps).

    Returns:
        float32[T, N] array where T = total time steps, N = n_workers.
        Each entry is the slowdown factor (>= 1.0) for that worker at that step.
    """
    total_steps = gpu_config.seconds_to_steps(sim_config.duration)
    N = sim_config.n_workers
    schedule = np.ones((total_steps, N), dtype=np.float32)

    for scenario in fault_config.scenarios:
        onset_step = gpu_config.seconds_to_steps(scenario.onset_time)
        if scenario.duration is not None:
            end_step = gpu_config.seconds_to_steps(scenario.onset_time + scenario.duration)
        else:
            end_step = total_steps

        for step in range(total_steps):
            t = gpu_config.steps_to_seconds(step)
            if step < onset_step or step >= end_step:
                continue

            slowdown = scenario.pattern.get_slowdown(t, scenario.onset_time)
            slowdown = max(1.0, slowdown)

            for node_idx in scenario.node_indices:
                schedule[step, node_idx] = max(schedule[step, node_idx], slowdown)

    return schedule
