"""S7: Recovery dynamics -- fault with finite duration, nodes recover."""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator.config import SimConfig, FaultConfig
from simulator.fault import FaultScenario, PermanentFault
from experiments.runner import ExperimentRunner, DEFAULT_BASELINES
from experiments.plots import generate_all_plots

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "results", "s7_recovery")


def make_fault_config(seed: int) -> FaultConfig:
    return FaultConfig(scenarios=[
        FaultScenario(
            node_indices=[0, 1],
            pattern=PermanentFault(slowdown=8.0),
            onset_time=15.0,
            duration=40.0,  # recovers at t=55s
        ),
    ])


def main() -> None:
    sim_config = SimConfig(n_workers=32, load_factor=0.80)

    runner = ExperimentRunner(name="s7_recovery", output_dir=OUTPUT_DIR)
    runner.run_all(
        fault_config_fn=make_fault_config,
        sim_config=sim_config,
        baselines=DEFAULT_BASELINES,
        n_runs=10,
        duration=100.0,
        warmup=5.0,
    )

    generate_all_plots(OUTPUT_DIR)
    print("\nS7 experiment complete.")


if __name__ == "__main__":
    main()
