"""S5: Fluctuating fault experiment -- oscillating slowdown on two nodes."""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator.config import SimConfig, FaultConfig
from simulator.fault import FaultScenario, FluctuatingFault
from experiments.runner import ExperimentRunner, DEFAULT_BASELINES
from experiments.plots import generate_all_plots

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "results", "s5_fluctuating")


def make_fault_config(seed: int) -> FaultConfig:
    return FaultConfig(scenarios=[
        FaultScenario(
            node_indices=[0, 1],
            pattern=FluctuatingFault(s_peak=5.0, d_on=8.0, d_off=8.0),
            onset_time=10.0,
        ),
    ])


def main() -> None:
    sim_config = SimConfig(n_workers=32, load_factor=0.80)

    runner = ExperimentRunner(name="s5_fluctuating", output_dir=OUTPUT_DIR)
    runner.run_all(
        fault_config_fn=make_fault_config,
        sim_config=sim_config,
        baselines=DEFAULT_BASELINES,
        n_runs=20,
        duration=120.0,
        warmup=10.0,
    )

    generate_all_plots(OUTPUT_DIR)
    print("\nS5 experiment complete.")


if __name__ == "__main__":
    main()
