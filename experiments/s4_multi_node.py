"""S4: Multi-node correlated failure.

32 nodes, 80% load, 4 nodes with PermanentFault (random slowdowns 2.0-5.0).
Tests system resilience when multiple nodes degrade simultaneously.
"""
from __future__ import annotations

import sys
import os

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator.config import SimConfig, FaultConfig
from simulator.fault import FaultScenario, PermanentFault
from experiments.runner import ExperimentRunner, DEFAULT_BASELINES
from experiments.plots import generate_all_plots


OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "results", "s4_multi_node")


def fault_config_fn(seed: int) -> FaultConfig:
    rng = np.random.default_rng(seed)
    slowdowns = rng.uniform(2.0, 5.0, size=4)
    scenarios = [
        FaultScenario(
            node_indices=[i],
            pattern=PermanentFault(slowdown=float(slowdowns[i])),
            onset_time=10.0,
        )
        for i in range(4)
    ]
    return FaultConfig(scenarios=scenarios)


def main() -> None:
    sim_config = SimConfig(
        n_workers=32,
        load_factor=0.8,
    )

    runner = ExperimentRunner(name="s4_multi_node", output_dir=OUTPUT_DIR)
    df = runner.run_all(
        fault_config_fn=fault_config_fn,
        sim_config=sim_config,
        baselines=DEFAULT_BASELINES,
        n_runs=20,
        duration=60.0,
        warmup=5.0,
    )

    generate_all_plots(OUTPUT_DIR)
    print(f"\nS4 experiment complete. Results in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
