"""S3: Flash crowd under slow fault.

32 nodes, two-wave load surge (70% -> 85% -> 70% -> 90% -> 70%), two permanent faults (3x).
Tests how strategies adapt when load surges while faults are active.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator.config import SimConfig, FaultConfig
from simulator.fault import FaultScenario, PermanentFault
from experiments.runner import ExperimentRunner, DEFAULT_BASELINES
from experiments.plots import generate_all_plots


OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "results", "s3_flash_crowd")


def fault_config_fn(seed: int) -> FaultConfig:
    return FaultConfig(
        scenarios=[
            FaultScenario(
                node_indices=[0, 1],
                pattern=PermanentFault(slowdown=3.0),
                onset_time=10.0,
            )
        ]
    )


def main() -> None:
    sim_config = SimConfig(
        n_workers=32,
        load_factor=0.7,  # base load; overridden by schedule
    )

    # Variable load schedule: 70% -> 85% -> 70% -> 90% -> 70%
    load_schedule = [
        (0.0, 0.7),
        (30.0, 0.85),
        (60.0, 0.7),
        (80.0, 0.90),
        (100.0, 0.7),
    ]

    runner = ExperimentRunner(name="s3_flash_crowd", output_dir=OUTPUT_DIR)
    df = runner.run_all(
        fault_config_fn=fault_config_fn,
        sim_config=sim_config,
        baselines=DEFAULT_BASELINES,
        n_runs=10,
        duration=100.0,
        warmup=5.0,
        load_schedule=load_schedule,
    )

    generate_all_plots(OUTPUT_DIR)
    print(f"\nS3 experiment complete. Results in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
