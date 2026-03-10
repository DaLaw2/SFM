"""S11: Literature baseline comparison.

Run all 8 baselines (5 original + 3 literature) across S2-S7 scenarios
to compare our adaptive framework against established approaches:
- lit_hedged: Unconditional hedged requests (Dean & Barroso 2013)
- lit_blacklist: Outlier blacklisting (Cassandra dynamic snitch style)
- lit_retry: Timeout-based retry (deadline = SLO/2)
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulator.config import SimConfig, FaultConfig, StrategyConfig
from simulator.fault import FaultScenario, PermanentFault, FluctuatingFault, ProgressiveFault

from experiments.runner import ExperimentRunner, ALL_BASELINES
from experiments.plots import generate_all_plots

import numpy as np

OUTPUT_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

N_RUNS = 10
DURATION = 60.0
WARMUP = 5.0
N_WORKERS = 32
LOAD_FACTOR = 0.8


def sim_config() -> SimConfig:
    return SimConfig(
        n_workers=N_WORKERS,
        load_factor=LOAD_FACTOR,
        duration=DURATION,
        warmup=WARMUP,
        slo_target=0.05,
    )


# --- Scenario fault configs (same as S2-S7) ---

def s2_fault(seed: int) -> FaultConfig:
    return FaultConfig(scenarios=[
        FaultScenario(
            node_indices=[0, 1],
            pattern=ProgressiveFault(beta=0.1, s_max=15.0),
            onset_time=10.0,
        ),
    ])

def s3_fault(seed: int) -> FaultConfig:
    return FaultConfig(scenarios=[
        FaultScenario(
            node_indices=[0, 1],
            pattern=PermanentFault(slowdown=3.0),
            onset_time=10.0,
        ),
    ])

def s4_fault(seed: int) -> FaultConfig:
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

def s5_fault(seed: int) -> FaultConfig:
    return FaultConfig(scenarios=[
        FaultScenario(
            node_indices=[0, 1],
            pattern=FluctuatingFault(s_peak=5.0, d_on=8.0, d_off=8.0),
            onset_time=10.0,
        ),
    ])

def s6_fault(seed: int) -> FaultConfig:
    return FaultConfig(scenarios=[
        FaultScenario(
            node_indices=[0],
            pattern=PermanentFault(slowdown=5.0),
            onset_time=10.0,
        ),
        FaultScenario(
            node_indices=[1],
            pattern=PermanentFault(slowdown=5.0),
            onset_time=25.0,
        ),
        FaultScenario(
            node_indices=[2],
            pattern=PermanentFault(slowdown=3.0),
            onset_time=40.0,
        ),
    ])

def s7_fault(seed: int) -> FaultConfig:
    return FaultConfig(scenarios=[
        FaultScenario(
            node_indices=[0, 1],
            pattern=PermanentFault(slowdown=8.0),
            onset_time=15.0,
            duration=40.0,  # recovers at t=55s
        ),
    ])


# (fault_fn, load_schedule, duration)
SCENARIOS = {
    "s2_progressive": (s2_fault, None, 60.0),
    "s3_flash_crowd": (s3_fault, [(0, 0.70), (15, 0.85), (25, 0.70), (35, 0.90), (45, 0.70)], 60.0),
    "s4_multi_node": (s4_fault, None, 60.0),
    "s5_fluctuating": (s5_fault, None, 60.0),
    "s6_cascade": (s6_fault, None, 90.0),
    "s7_recovery": (s7_fault, None, 100.0),
}


def run_s11():
    for scenario_name, (fault_fn, load_schedule, duration) in SCENARIOS.items():
        output_dir = os.path.join(OUTPUT_BASE, f"s11_{scenario_name}")
        print(f"\n{'='*60}")
        print(f"S11: {scenario_name}")
        print(f"{'='*60}")

        n_runs = 20 if scenario_name == "s4_multi_node" else N_RUNS

        runner = ExperimentRunner(
            name=f"s11_{scenario_name}",
            output_dir=output_dir,
        )
        df = runner.run_all(
            fault_config_fn=fault_fn,
            sim_config=sim_config(),
            baselines=ALL_BASELINES,
            n_runs=n_runs,
            duration=duration,
            warmup=WARMUP,
            load_schedule=load_schedule,
        )

        try:
            generate_all_plots(output_dir)
        except Exception as e:
            print(f"  Plot failed: {e}")

    print(f"\n{'='*60}")
    print("S11 literature comparison complete!")
    print(f"{'='*60}")


if __name__ == "__main__":
    run_s11()
