"""S1: Single node severity sweep at 80% load.

Sweep slowdown factor on 1 node across all baselines.
- 32 nodes, 80% load
- Slowdown values: [1.0, 1.05, 1.1, 1.15, 1.2, 1.3, 1.5, 2.0, 3.0, 5.0, 10.0]
- 5 baselines x 10 runs per slowdown value
- Save to experiments/results/s1_severity_sweep/
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
from experiments.runner import DEFAULT_BASELINES
from experiments.plots import BASELINE_COLORS, BASELINE_LABELS

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "s1_severity_sweep")
SLOWDOWNS = [1.0, 1.05, 1.1, 1.15, 1.2, 1.3, 1.5, 2.0, 3.0, 5.0, 10.0]
N_RUNS = 10
DURATION = 60.0
WARMUP = 10.0
N_WORKERS = 32
LOAD_FACTOR = 0.8


def _run_single_s1(
    slowdown: float,
    baseline_name: str,
    enable_mitigation: bool,
    strategy_config: StrategyConfig,
    run_id: int,
    seed: int,
) -> dict:
    """Top-level function for ProcessPoolExecutor (must be picklable)."""
    from simulator.run import run_simulation

    sim_config = SimConfig(
        n_workers=N_WORKERS,
        load_factor=LOAD_FACTOR,
        duration=DURATION,
        warmup=WARMUP,
        seed=seed,
    )

    fault_cfg = FaultConfig()
    if slowdown > 1.0:
        fault_cfg.scenarios = [FaultScenario(
            node_indices=[0],
            pattern=PermanentFault(slowdown=slowdown),
            onset_time=0.0,
        )]

    t0 = time.time()
    stats = run_simulation(
        config=sim_config,
        fault_config=fault_cfg,
        strategy_config=strategy_config,
        enable_mitigation=enable_mitigation,
        verbose=False,
    )
    elapsed = time.time() - t0

    return {
        "slowdown": slowdown,
        "baseline": baseline_name,
        "run_id": run_id,
        "seed": seed,
        "elapsed_sec": elapsed,
        **stats,
    }


def run_s1():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Build all jobs
    jobs: list[dict] = []
    for s in SLOWDOWNS:
        for bl in DEFAULT_BASELINES:
            for run_id in range(N_RUNS):
                seed = abs(hash((bl.name, s, run_id))) % 100000
                jobs.append({
                    "slowdown": s,
                    "baseline_name": bl.name,
                    "enable_mitigation": bl.enable_mitigation,
                    "strategy_config": bl.strategy_config or StrategyConfig(),
                    "run_id": run_id,
                    "seed": seed,
                })

    total = len(jobs)
    max_workers = max(1, (os.cpu_count() or 1) - 1)
    print(f"Running {total} jobs ({len(SLOWDOWNS)} slowdowns x "
          f"{len(DEFAULT_BASELINES)} baselines x {N_RUNS} runs) "
          f"with up to {max_workers} workers...")

    all_results: list[dict] = []
    t_start = time.time()

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_run_single_s1, **job): job
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
                print(f"  FAILED: {job['baseline_name']} s={job['slowdown']} "
                      f"run {job['run_id']}: {e}")

    total_time = time.time() - t_start
    print(f"All {total} jobs completed in {total_time:.1f}s")

    df = pd.DataFrame(all_results)

    # Save raw results
    csv_path = os.path.join(OUTPUT_DIR, "raw_results.csv")
    df.to_csv(csv_path, index=False)
    print(f"\nRaw results saved to {csv_path}")

    # Compute summary (mean + CI per slowdown per baseline)
    summary_rows = []
    for (s, bl_name), group in df.groupby(["slowdown", "baseline"]):
        n = len(group)
        for metric in [
                "p99_latency", "p999_latency", "p95_latency", "p50_latency",
                "avg_latency", "max_latency", "tail_ratio",
                "throughput", "goodput", "slo_violation_rate", "affected_ratio",
            ]:
            if metric not in group.columns:
                continue
            values = group[metric].values
            mean = values.mean()
            if n > 1:
                se = values.std(ddof=1) / np.sqrt(n)
                ci = sp_stats.t.ppf(0.975, n - 1) * se
            else:
                ci = 0.0
            summary_rows.append({
                "slowdown": s,
                "baseline": bl_name,
                "metric": metric,
                "mean": mean,
                "ci_95": ci,
                "min": values.min(),
                "max": values.max(),
                "n": n,
            })

    summary_df = pd.DataFrame(summary_rows)
    summary_path = os.path.join(OUTPUT_DIR, "summary.csv")
    summary_df.to_csv(summary_path, index=False)
    print(f"Summary saved to {summary_path}")

    # Save metadata
    meta = {
        "name": "s1_severity_sweep",
        "slowdowns": SLOWDOWNS,
        "n_runs": N_RUNS,
        "duration": DURATION,
        "warmup": WARMUP,
        "n_workers": N_WORKERS,
        "load_factor": LOAD_FACTOR,
        "baselines": [{"name": b.name, "description": b.description} for b in DEFAULT_BASELINES],
        "parallelism": max_workers,
        "total_wall_time_sec": total_time,
    }
    meta_path = os.path.join(OUTPUT_DIR, "metadata.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    # Generate plots
    _plot_p99_vs_slowdown(df)
    _plot_throughput_vs_slowdown(df)

    print("\nS1 experiment complete!")
    return df


def _plot_p99_vs_slowdown(df: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(10, 6))

    for bl_name, group in df.groupby("baseline"):
        color = BASELINE_COLORS.get(bl_name, "gray")
        label = BASELINE_LABELS.get(bl_name, bl_name)
        means = group.groupby("slowdown")["p99_latency"].mean() * 1000
        sems = group.groupby("slowdown")["p99_latency"].sem() * 1000
        ax.plot(means.index, means.values, "o-", color=color, label=label, linewidth=2, markersize=4)
        ax.fill_between(means.index, means.values - 1.96 * sems.values,
                        means.values + 1.96 * sems.values, alpha=0.15, color=color)

    ax.axhline(y=50, color="red", linestyle="--", alpha=0.5, label="SLO = 50ms")
    ax.set_xlabel("Slowdown Factor", fontsize=12)
    ax.set_ylabel("System P99 Latency (ms)", fontsize=12)
    ax.set_title("S1: P99 Latency vs Slowdown Factor (32 nodes, 80% load)", fontsize=13)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    out_path = os.path.join(OUTPUT_DIR, "p99_vs_slowdown.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Plot saved to {out_path}")


def _plot_throughput_vs_slowdown(df: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(10, 6))

    for bl_name, group in df.groupby("baseline"):
        color = BASELINE_COLORS.get(bl_name, "gray")
        label = BASELINE_LABELS.get(bl_name, bl_name)
        means = group.groupby("slowdown")["throughput"].mean()
        sems = group.groupby("slowdown")["throughput"].sem()
        ax.plot(means.index, means.values, "o-", color=color, label=label, linewidth=2, markersize=4)
        ax.fill_between(means.index, means.values - 1.96 * sems.values,
                        means.values + 1.96 * sems.values, alpha=0.15, color=color)

    ax.set_xlabel("Slowdown Factor", fontsize=12)
    ax.set_ylabel("Throughput (req/s)", fontsize=12)
    ax.set_title("S1: Throughput vs Slowdown Factor (32 nodes, 80% load)", fontsize=13)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    out_path = os.path.join(OUTPUT_DIR, "throughput_vs_slowdown.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Plot saved to {out_path}")


if __name__ == "__main__":
    run_s1()
