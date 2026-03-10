"""S2: Progressive thermal throttling (GPU thermal model).

2 nodes with progressive fault: s(t) = 1.0 + 0.1*(t-15), onset=15s, s_max=15.0
- 32 nodes, 80% load, duration=120s, warmup=10s
- 5 baselines x 10 runs
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulator.config import SimConfig, FaultConfig, StrategyConfig
from simulator.fault import FaultScenario, ProgressiveFault
from experiments.runner import ExperimentRunner, DEFAULT_BASELINES
from experiments.plots import plot_comparison_bar

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "s2_progressive")
N_RUNS = 10
DURATION = 120.0
WARMUP = 10.0
N_WORKERS = 32
LOAD_FACTOR = 0.8


def _fault_config_fn(seed: int) -> FaultConfig:
    return FaultConfig(
        scenarios=[FaultScenario(
            node_indices=[0, 1],
            pattern=ProgressiveFault(beta=0.1, s_max=15.0),
            onset_time=15.0,
        )]
    )


def run_s2():
    sim_config = SimConfig(
        n_workers=N_WORKERS,
        load_factor=LOAD_FACTOR,
    )

    runner = ExperimentRunner(name="s2_progressive", output_dir=OUTPUT_DIR)
    df = runner.run_all(
        fault_config_fn=_fault_config_fn,
        sim_config=sim_config,
        baselines=DEFAULT_BASELINES,
        n_runs=N_RUNS,
        duration=DURATION,
        warmup=WARMUP,
    )

    # Plots
    import pandas as pd
    summary_path = os.path.join(OUTPUT_DIR, "summary.csv")
    summary_df = pd.read_csv(summary_path)

    plot_comparison_bar(
        summary_df, "p99_latency",
        os.path.join(OUTPUT_DIR, "p99_comparison.png"),
        title="S2: P99 Latency - Progressive Throttling (32 nodes, 80% load)",
        ylabel="P99 Latency (ms)",
        multiply=1000,
        slo_line=50,
    )

    plot_comparison_bar(
        summary_df, "throughput",
        os.path.join(OUTPUT_DIR, "throughput_comparison.png"),
        title="S2: Throughput - Progressive Throttling (32 nodes, 80% load)",
        ylabel="Throughput (req/s)",
    )

    print("\nS2 experiment complete!")
    return df


if __name__ == "__main__":
    run_s2()
