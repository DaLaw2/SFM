"""S12: High-load stress test for fixed_isolation vs adaptive.

At high load (85-90%), removing faulty nodes entirely (isolation) reduces
effective cluster capacity, potentially causing cascading overload.
This experiment tests whether adaptive's graduated response (SHED before
ISOLATE) outperforms fixed_isolation in this regime.

Configurations:
- Load factors: 0.80, 0.85, 0.88, 0.90
- Fault scenarios: S3-style (2 nodes, 3x, flash crowd), S4-style (4 nodes, mixed),
  S6-style (cascade 1→2→3 nodes)
- Baselines: adaptive, fixed_isolation, lit_blacklist, no_mitigation
- 10 runs each
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulator.config import SimConfig, FaultConfig, StrategyConfig
from simulator.fault import FaultScenario, PermanentFault

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "s12_highload_isolation")

LOAD_FACTORS = [0.80, 0.85, 0.88, 0.90]
N_RUNS = 10
DURATION = 60.0
WARMUP = 5.0
N_WORKERS = 32
SLO_TARGET = 0.05  # 50ms

BASELINES = [
    ("adaptive", True, StrategyConfig(), None),
    ("fixed_isolation", True, StrategyConfig(theta_spec=999.0, theta_shed=999.0, theta_iso=0.3), None),
    ("lit_blacklist", False, StrategyConfig(), "blacklist"),
    ("no_mitigation", False, StrategyConfig(), None),
]

# Fault scenarios that stress isolation
def s3_style_fault(seed: int) -> FaultConfig:
    """2 nodes at 3x — moderate fault, isolation removes 6.25% capacity."""
    return FaultConfig(scenarios=[
        FaultScenario(
            node_indices=[0, 1],
            pattern=PermanentFault(slowdown=3.0),
            onset_time=10.0,
        ),
    ])

def s4_style_fault(seed: int) -> FaultConfig:
    """4 nodes at mixed severity — isolation removes 12.5% capacity."""
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

def s6_style_fault(seed: int) -> FaultConfig:
    """Cascade: 1→2→3 nodes — isolation removes up to 9.4% capacity."""
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


FAULT_SCENARIOS = {
    "s3_2node_3x": (s3_style_fault, None),
    "s4_4node_mixed": (s4_style_fault, None),
    "s6_cascade": (s6_style_fault, None),
}


def _run_single(
    load_factor: float,
    fault_scenario: str,
    fault_config: FaultConfig,
    baseline_name: str,
    enable_mitigation: bool,
    strategy_config: StrategyConfig,
    mitigation_mode: str | None,
    load_schedule: list[tuple[float, float]] | None,
    run_id: int,
    seed: int,
) -> dict:
    from simulator.run import run_simulation

    sim_config = SimConfig(
        n_workers=N_WORKERS,
        load_factor=load_factor,
        duration=DURATION,
        warmup=WARMUP,
        slo_target=SLO_TARGET,
        seed=seed,
    )

    t0 = time.time()
    stats = run_simulation(
        config=sim_config,
        fault_config=fault_config,
        strategy_config=strategy_config,
        enable_mitigation=enable_mitigation,
        verbose=False,
        load_schedule=load_schedule,
        mitigation_mode=mitigation_mode,
    )
    elapsed = time.time() - t0

    return {
        "load_factor": load_factor,
        "fault_scenario": fault_scenario,
        "baseline": baseline_name,
        "run_id": run_id,
        "seed": seed,
        "elapsed_sec": elapsed,
        **stats,
    }


def run_s12():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    jobs: list[dict] = []
    for lf in LOAD_FACTORS:
        for sc_name, (fault_fn, load_schedule) in FAULT_SCENARIOS.items():
            for bl_name, bl_enable, bl_cfg, bl_mode in BASELINES:
                for run_id in range(N_RUNS):
                    seed = abs(hash((bl_name, lf, sc_name, run_id))) % 100000
                    jobs.append({
                        "load_factor": lf,
                        "fault_scenario": sc_name,
                        "fault_config": fault_fn(seed),
                        "baseline_name": bl_name,
                        "enable_mitigation": bl_enable,
                        "strategy_config": bl_cfg,
                        "mitigation_mode": bl_mode,
                        "load_schedule": load_schedule,
                        "run_id": run_id,
                        "seed": seed,
                    })

    total = len(jobs)
    max_workers = max(1, (os.cpu_count() or 1) - 1)
    print(f"Running {total} jobs ({len(LOAD_FACTORS)} loads x {len(FAULT_SCENARIOS)} "
          f"scenarios x {len(BASELINES)} baselines x {N_RUNS} runs) "
          f"with up to {max_workers} workers...")

    all_results: list[dict] = []
    t_start = time.time()

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_run_single, **job): job
            for job in jobs
        }
        done_count = 0
        for future in as_completed(futures):
            done_count += 1
            try:
                result = future.result()
                all_results.append(result)
                if done_count % 20 == 0 or done_count == total:
                    elapsed = time.time() - t_start
                    print(f"  [{done_count}/{total}] {elapsed:.0f}s elapsed")
            except Exception as e:
                job = futures[future]
                print(f"  FAILED: {job['baseline_name']} lf={job['load_factor']} "
                      f"{job['fault_scenario']} run {job['run_id']}: {e}")

    total_time = time.time() - t_start
    print(f"All {total} jobs completed in {total_time:.1f}s")

    df = pd.DataFrame(all_results)

    csv_path = os.path.join(OUTPUT_DIR, "raw_results.csv")
    df.to_csv(csv_path, index=False)
    print(f"\nRaw results saved to {csv_path}")

    # Summary
    summary_rows = []
    for (lf, sc, bl), group in df.groupby(["load_factor", "fault_scenario", "baseline"]):
        n = len(group)
        for metric in [
            "p99_latency", "p999_latency", "p95_latency", "p50_latency",
            "avg_latency", "throughput", "goodput", "slo_violation_rate",
        ]:
            if metric not in group.columns:
                continue
            values = group[metric].values
            mean = values.mean()
            ci = sp_stats.t.ppf(0.975, n - 1) * values.std(ddof=1) / np.sqrt(n) if n > 1 else 0.0
            summary_rows.append({
                "load_factor": lf,
                "fault_scenario": sc,
                "baseline": bl,
                "metric": metric,
                "mean": mean,
                "ci_95": ci,
                "n": n,
            })

    summary_df = pd.DataFrame(summary_rows)
    summary_path = os.path.join(OUTPUT_DIR, "summary.csv")
    summary_df.to_csv(summary_path, index=False)
    print(f"Summary saved to {summary_path}")

    meta = {
        "name": "s12_highload_isolation",
        "load_factors": LOAD_FACTORS,
        "fault_scenarios": list(FAULT_SCENARIOS.keys()),
        "n_runs": N_RUNS,
        "duration": DURATION,
        "warmup": WARMUP,
        "n_workers": N_WORKERS,
        "slo_target_ms": SLO_TARGET * 1000,
        "baselines": [b[0] for b in BASELINES],
        "total_wall_time_sec": total_time,
    }
    with open(os.path.join(OUTPUT_DIR, "metadata.json"), "w") as f:
        json.dump(meta, f, indent=2)

    _plot_results(df)
    print("\nS12 experiment complete!")
    return df


def _plot_results(df: pd.DataFrame):
    """Plot P99 by load factor for each scenario, comparing baselines."""
    baseline_order = ["adaptive", "fixed_isolation", "lit_blacklist", "no_mitigation"]
    colors = {"adaptive": "#2ca02c", "fixed_isolation": "#1f77b4",
              "lit_blacklist": "#ff7f0e", "no_mitigation": "#d62728"}

    for sc_name in FAULT_SCENARIOS:
        fig, ax = plt.subplots(figsize=(8, 5))

        for bl in baseline_order:
            sub = df[(df.fault_scenario == sc_name) & (df.baseline == bl)]
            if sub.empty:
                continue
            means = sub.groupby("load_factor")["p99_latency"].mean() * 1000
            stds = sub.groupby("load_factor")["p99_latency"].std() * 1000
            ax.errorbar(means.index, means.values, yerr=stds.values,
                        marker="o", linewidth=2, capsize=4, label=bl,
                        color=colors.get(bl, "gray"))

        ax.axhline(y=SLO_TARGET * 1000, color="gray", linestyle="--", alpha=0.7, label="SLO 50ms")
        ax.set_xlabel("Load Factor", fontsize=12)
        ax.set_ylabel("P99 Latency (ms)", fontsize=12)
        ax.set_title(f"S12: {sc_name} — P99 vs Load Factor", fontsize=13)
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.set_yscale("log")
        fig.tight_layout()

        out_path = os.path.join(OUTPUT_DIR, f"p99_vs_load_{sc_name}.png")
        fig.savefig(out_path, dpi=150)
        plt.close(fig)
        print(f"Plot saved to {out_path}")


if __name__ == "__main__":
    run_s12()
