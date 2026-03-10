"""S14: Adaptive framework differentiation experiments.

Test scenarios where adaptive's graduated SHED strategy should outperform
fixed_isolation's binary isolate-or-nothing approach:

  E1: Many moderate faults (8 nodes at 2x) — isolation infeasible
  E2: Mixed severity (2x severe + 2x moderate + 2x mild) — graduated response needed
  E3: Progressive degradation (4 nodes, 1x→8x over 30s)
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulator.config import SimConfig, FaultConfig, StrategyConfig
from simulator.fault import FaultScenario, PermanentFault, ProgressiveFault
from experiments.runner import DEFAULT_BASELINES, LITERATURE_BASELINES, Baseline

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "s14_adaptive_diff")
N_RUNS = 10
DURATION = 60.0
WARMUP = 10.0
N_WORKERS = 32

# Key baselines for comparison
KEY_BASELINES = [b for b in DEFAULT_BASELINES
                 if b.name in ("no_mitigation", "fixed_isolation", "adaptive")]
# Add lit_blacklist
KEY_BASELINES.append(next(b for b in LITERATURE_BASELINES if b.name == "lit_blacklist"))


EXPERIMENTS = {
    "E1_many_moderate": {
        "description": "8 nodes at 2x slowdown (25% of cluster, isolation infeasible)",
        "load_factors": [0.70, 0.75, 0.80, 0.85],
        "fault_fn": lambda seed: FaultConfig(scenarios=[
            FaultScenario(
                node_indices=list(range(8)),
                pattern=PermanentFault(slowdown=2.0),
                onset_time=10.0,
            ),
        ]),
    },
    "E2_mixed_severity": {
        "description": "6 nodes: 2x8x + 2x3x + 2x1.5x (graduated severity)",
        "load_factors": [0.75, 0.80, 0.85],
        "fault_fn": lambda seed: FaultConfig(scenarios=[
            FaultScenario(node_indices=[0, 1], pattern=PermanentFault(slowdown=8.0), onset_time=10.0),
            FaultScenario(node_indices=[2, 3], pattern=PermanentFault(slowdown=3.0), onset_time=10.0),
            FaultScenario(node_indices=[4, 5], pattern=PermanentFault(slowdown=1.5), onset_time=10.0),
        ]),
    },
    "E3_progressive": {
        "description": "4 nodes progressive 1x→8x over 30s",
        "load_factors": [0.75, 0.80, 0.85],
        "fault_fn": lambda seed: FaultConfig(scenarios=[
            FaultScenario(
                node_indices=[0, 1, 2, 3],
                pattern=ProgressiveFault(beta=0.233, s_max=8.0),
                onset_time=10.0,
            ),
        ]),
    },
}


def _run_single(
    experiment: str,
    load_factor: float,
    baseline_name: str,
    enable_mitigation: bool,
    strategy_config: StrategyConfig,
    run_id: int,
    seed: int,
    mitigation_mode: str | None = None,
) -> dict:
    from simulator.run import run_simulation

    fault_config = EXPERIMENTS[experiment]["fault_fn"](seed)
    sim_config = SimConfig(
        n_workers=N_WORKERS,
        load_factor=load_factor,
        duration=DURATION,
        warmup=WARMUP,
        seed=seed,
    )
    t0 = time.time()
    stats = run_simulation(
        config=sim_config,
        fault_config=fault_config,
        strategy_config=strategy_config,
        enable_mitigation=enable_mitigation,
        verbose=False,
        mitigation_mode=mitigation_mode,
    )
    return {
        "experiment": experiment,
        "load_factor": load_factor,
        "baseline": baseline_name,
        "run_id": run_id,
        "seed": seed,
        "elapsed_sec": time.time() - t0,
        **stats,
    }


def run_s14():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    base_seed = 42

    jobs = []
    for exp_name, exp_cfg in EXPERIMENTS.items():
        for lf in exp_cfg["load_factors"]:
            for bl in KEY_BASELINES:
                for run_id in range(N_RUNS):
                    jobs.append({
                        "experiment": exp_name,
                        "load_factor": lf,
                        "baseline_name": bl.name,
                        "enable_mitigation": bl.enable_mitigation,
                        "strategy_config": bl.strategy_config or StrategyConfig(),
                        "run_id": run_id,
                        "seed": base_seed + run_id,
                        "mitigation_mode": bl.mitigation_mode,
                    })

    total = len(jobs)
    max_workers = max(1, (os.cpu_count() or 1) - 1)
    print(f"Running {total} jobs across {len(EXPERIMENTS)} experiments...")

    results = []
    t_start = time.time()
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_single, **j): j for j in jobs}
        done = 0
        for f in as_completed(futures):
            done += 1
            try:
                results.append(f.result())
                if done % 20 == 0 or done == total:
                    print(f"  [{done}/{total}] {time.time() - t_start:.0f}s")
            except Exception as e:
                job = futures[f]
                print(f"  FAILED: {job['experiment']}/{job['baseline_name']} L={job['load_factor']}: {e}")

    print(f"All done in {time.time() - t_start:.1f}s")

    df = pd.DataFrame(results)
    df.to_csv(os.path.join(OUTPUT_DIR, "raw_results.csv"), index=False)

    # Analysis per experiment
    for exp_name in EXPERIMENTS:
        exp_df = df[df["experiment"] == exp_name]
        print(f"\n{'='*60}")
        print(f"{exp_name}: {EXPERIMENTS[exp_name]['description']}")
        print(f"{'='*60}")

        print(f"\n  P99 (ms) by load factor:")
        print(f"  {'Baseline':<18}", end="")
        for lf in EXPERIMENTS[exp_name]["load_factors"]:
            print(f"  L={lf:4.2f}", end="")
        print()

        for bl in KEY_BASELINES:
            print(f"  {bl.name:<18}", end="")
            for lf in EXPERIMENTS[exp_name]["load_factors"]:
                val = exp_df[(exp_df["baseline"] == bl.name) & (exp_df["load_factor"] == lf)]["p99_latency"].mean() * 1000
                print(f"  {val:7.1f}", end="")
            print()

        # Minimax regret
        print(f"\n  Minimax regret (ms):")
        print(f"  {'Baseline':<18} {'Max':>8} {'Avg':>8}")
        load_factors = EXPERIMENTS[exp_name]["load_factors"]
        for bl in KEY_BASELINES:
            regrets = []
            for lf in load_factors:
                sub = exp_df[exp_df["load_factor"] == lf]
                best = sub.groupby("baseline")["p99_latency"].mean().min() * 1000
                val = sub[sub["baseline"] == bl.name]["p99_latency"].mean() * 1000
                regrets.append(val - best)
            print(f"  {bl.name:<18} {max(regrets):8.1f} {np.mean(regrets):8.1f}")

    # Summary
    summary = df.groupby(["experiment", "load_factor", "baseline"]).agg(
        p99_mean=("p99_latency", "mean"),
        p99_std=("p99_latency", "std"),
        p999_mean=("p999_latency", "mean"),
        slo_viol=("slo_violation_rate", "mean"),
    ).reset_index()
    summary["p99_ms"] = summary["p99_mean"] * 1000
    summary.to_csv(os.path.join(OUTPUT_DIR, "summary.csv"), index=False)

    meta = {
        "name": "s14_adaptive_differentiation",
        "experiments": {k: v["description"] for k, v in EXPERIMENTS.items()},
        "n_runs": N_RUNS,
        "n_workers": N_WORKERS,
        "baselines": [b.name for b in KEY_BASELINES],
    }
    with open(os.path.join(OUTPUT_DIR, "metadata.json"), "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nS14 complete! Results in {OUTPUT_DIR}")
    return df


if __name__ == "__main__":
    run_s14()
