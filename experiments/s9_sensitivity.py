"""S9: Parameter sensitivity analysis.

Vary 3 key parameters (decision_epoch, theta_iso, debounce) with ±20-50%
perturbation on S4 (hardest passing scenario) to assess robustness.

Goal: determine if adaptive performance is robust to parameter variation
or requires precise tuning.
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
from experiments.plots import BASELINE_COLORS

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "s9_sensitivity")

# Parameter variations: (param_name, values, default)
PARAMS = {
    "decision_epoch": ([0.25, 0.5, 1.0, 2.0], 0.5),
    "theta_iso": ([0.3, 0.4, 0.5, 0.6, 0.7], 0.5),
    "debounce": ([1, 2, 3, 4], 2),
}

N_RUNS = 10
N_WORKERS = 32
LOAD_FACTOR = 0.8


def _make_s4_fault(seed: int) -> FaultConfig:
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


def _run_single(
    param_name: str,
    param_value: float,
    run_id: int,
    seed: int,
    decision_epoch: float,
    theta_iso: float,
    debounce: int,
) -> dict:
    from simulator.run import run_simulation

    sim_config = SimConfig(
        n_workers=N_WORKERS,
        load_factor=LOAD_FACTOR,
        duration=60.0,
        warmup=5.0,
        seed=seed,
        decision_epoch=decision_epoch,
    )

    strategy_config = StrategyConfig(
        theta_iso=theta_iso,
        debounce=debounce,
    )

    fault_config = _make_s4_fault(seed)

    t0 = time.time()
    stats = run_simulation(
        config=sim_config,
        fault_config=fault_config,
        strategy_config=strategy_config,
        enable_mitigation=True,
        verbose=False,
    )
    elapsed = time.time() - t0

    return {
        "param_name": param_name,
        "param_value": param_value,
        "run_id": run_id,
        "seed": seed,
        "elapsed_sec": elapsed,
        **stats,
    }


def run_s9():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    jobs: list[dict] = []
    for param_name, (values, default) in PARAMS.items():
        for val in values:
            for run_id in range(N_RUNS):
                seed = abs(hash((param_name, val, run_id))) % 100000
                # Set all params to default, then override the one being varied
                kwargs = {
                    "decision_epoch": PARAMS["decision_epoch"][1],
                    "theta_iso": PARAMS["theta_iso"][1],
                    "debounce": PARAMS["debounce"][1],
                }
                kwargs[param_name] = val if param_name != "debounce" else int(val)

                jobs.append({
                    "param_name": param_name,
                    "param_value": float(val),
                    "run_id": run_id,
                    "seed": seed,
                    **kwargs,
                })

    total = len(jobs)
    max_workers = max(1, (os.cpu_count() or 1) - 1)
    print(f"Running {total} jobs ({sum(len(v[0]) for v in PARAMS.values())} param values "
          f"x {N_RUNS} runs) with up to {max_workers} workers...")

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
                print(f"  FAILED: {job['param_name']}={job['param_value']} "
                      f"run {job['run_id']}: {e}")

    total_time = time.time() - t_start
    print(f"All {total} jobs completed in {total_time:.1f}s")

    df = pd.DataFrame(all_results)

    csv_path = os.path.join(OUTPUT_DIR, "raw_results.csv")
    df.to_csv(csv_path, index=False)
    print(f"\nRaw results saved to {csv_path}")

    # Summary
    summary_rows = []
    for (pn, pv), group in df.groupby(["param_name", "param_value"]):
        n = len(group)
        for metric in ["p99_latency", "p999_latency", "slo_violation_rate", "goodput"]:
            if metric not in group.columns:
                continue
            values = group[metric].values
            mean = values.mean()
            se = values.std(ddof=1) / np.sqrt(n) if n > 1 else 0
            ci = sp_stats.t.ppf(0.975, n - 1) * se if n > 1 else 0
            summary_rows.append({
                "param_name": pn, "param_value": pv, "metric": metric,
                "mean": mean, "ci_95": ci, "min": values.min(), "max": values.max(), "n": n,
            })

    summary_df = pd.DataFrame(summary_rows)
    summary_path = os.path.join(OUTPUT_DIR, "summary.csv")
    summary_df.to_csv(summary_path, index=False)
    print(f"Summary saved to {summary_path}")

    meta = {
        "name": "s9_sensitivity",
        "params": {k: {"values": v[0], "default": v[1]} for k, v in PARAMS.items()},
        "n_runs": N_RUNS, "n_workers": N_WORKERS, "load_factor": LOAD_FACTOR,
        "scenario": "S4 (4 faults, random 2-5x, 32 nodes)",
        "total_wall_time_sec": total_time,
    }
    with open(os.path.join(OUTPUT_DIR, "metadata.json"), "w") as f:
        json.dump(meta, f, indent=2)

    _plot_sensitivity(summary_df)
    print("\nS9 experiment complete!")
    return df


def _plot_sensitivity(summary_df: pd.DataFrame):
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    for ax, param_name in zip(axes, PARAMS.keys()):
        values, default = PARAMS[param_name]
        subset = summary_df[
            (summary_df["param_name"] == param_name) &
            (summary_df["metric"] == "p99_latency")
        ].sort_values("param_value")

        means = subset["mean"].values * 1000
        cis = subset["ci_95"].values * 1000
        xs = subset["param_value"].values

        ax.errorbar(xs, means, yerr=cis, fmt="o-", color="#1f77b4",
                    linewidth=2, markersize=8, capsize=5)
        ax.axhline(y=50, color="red", linestyle="--", alpha=0.5, label="SLO 50ms")
        ax.axvline(x=default, color="gray", linestyle=":", alpha=0.5, label=f"default={default}")
        ax.set_xlabel(param_name, fontsize=12)
        ax.set_ylabel("P99 Latency (ms)", fontsize=12)
        ax.set_title(f"Sensitivity to {param_name}", fontsize=12)
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

    fig.suptitle("S9: Parameter Sensitivity on S4 (4 faults, random 2-5x)", fontsize=14)
    fig.tight_layout()

    out_path = os.path.join(OUTPUT_DIR, "sensitivity.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Plot saved to {out_path}")


if __name__ == "__main__":
    run_s9()
