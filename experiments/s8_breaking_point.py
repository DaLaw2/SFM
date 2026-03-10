"""S8: Breaking-point analysis — sweep fault fraction and severity.

32 nodes, 80% load. Sweep:
- Fault node count: 4, 8, 12, 16 (12.5% to 50%)
- Fault severity: 3x, 5x, 10x, 20x
- All faults are permanent, onset at warmup boundary

Goal: find where adaptive strategy's P99 crosses the 50ms SLO target.
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

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "s8_breaking_point")
FAULT_COUNTS = [4, 8, 12, 16]
SEVERITIES = [3.0, 5.0, 10.0, 20.0]
N_RUNS = 10
DURATION = 60.0
WARMUP = 5.0
N_WORKERS = 32
LOAD_FACTOR = 0.8


def _run_single_s8(
    n_faults: int,
    slowdown: float,
    baseline_name: str,
    enable_mitigation: bool,
    strategy_config: StrategyConfig,
    run_id: int,
    seed: int,
) -> dict:
    from simulator.run import run_simulation

    sim_config = SimConfig(
        n_workers=N_WORKERS,
        load_factor=LOAD_FACTOR,
        duration=DURATION,
        warmup=WARMUP,
        seed=seed,
    )

    fault_cfg = FaultConfig(scenarios=[
        FaultScenario(
            node_indices=list(range(n_faults)),
            pattern=PermanentFault(slowdown=slowdown),
            onset_time=5.0,
        ),
    ])

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
        "n_faults": n_faults,
        "slowdown": slowdown,
        "baseline": baseline_name,
        "run_id": run_id,
        "seed": seed,
        "elapsed_sec": elapsed,
        **stats,
    }


def run_s8():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    jobs: list[dict] = []
    for nf in FAULT_COUNTS:
        for sev in SEVERITIES:
            for bl in DEFAULT_BASELINES:
                for run_id in range(N_RUNS):
                    seed = abs(hash((bl.name, nf, sev, run_id))) % 100000
                    jobs.append({
                        "n_faults": nf,
                        "slowdown": sev,
                        "baseline_name": bl.name,
                        "enable_mitigation": bl.enable_mitigation,
                        "strategy_config": bl.strategy_config or StrategyConfig(),
                        "run_id": run_id,
                        "seed": seed,
                    })

    total = len(jobs)
    max_workers = max(1, (os.cpu_count() or 1) - 1)
    print(f"Running {total} jobs ({len(FAULT_COUNTS)} fault counts x "
          f"{len(SEVERITIES)} severities x {len(DEFAULT_BASELINES)} baselines x "
          f"{N_RUNS} runs) with up to {max_workers} workers...")

    all_results: list[dict] = []
    t_start = time.time()

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_run_single_s8, **job): job
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
                print(f"  FAILED: {job['baseline_name']} nf={job['n_faults']} "
                      f"s={job['slowdown']} run {job['run_id']}: {e}")

    total_time = time.time() - t_start
    print(f"All {total} jobs completed in {total_time:.1f}s")

    df = pd.DataFrame(all_results)

    csv_path = os.path.join(OUTPUT_DIR, "raw_results.csv")
    df.to_csv(csv_path, index=False)
    print(f"\nRaw results saved to {csv_path}")

    # Compute summary
    summary_rows = []
    for (nf, sev, bl_name), group in df.groupby(["n_faults", "slowdown", "baseline"]):
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
                "n_faults": nf,
                "slowdown": sev,
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

    meta = {
        "name": "s8_breaking_point",
        "fault_counts": FAULT_COUNTS,
        "severities": SEVERITIES,
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

    _plot_heatmap(summary_df)
    _plot_p99_curves(df)

    print("\nS8 experiment complete!")
    return df


def _plot_heatmap(summary_df: pd.DataFrame):
    """Heatmap of adaptive P99 vs fault count and severity."""
    adaptive = summary_df[
        (summary_df["baseline"] == "adaptive") &
        (summary_df["metric"] == "p99_latency")
    ]
    if adaptive.empty:
        return

    pivot = adaptive.pivot_table(
        index="n_faults", columns="slowdown", values="mean"
    ) * 1000  # to ms

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(pivot.values, cmap="RdYlGn_r", aspect="auto",
                   vmin=20, vmax=200)
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([f"{s:.0f}x" for s in pivot.columns])
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([f"{nf} ({nf*100//N_WORKERS}%)" for nf in pivot.index])
    ax.set_xlabel("Fault Severity", fontsize=12)
    ax.set_ylabel("Fault Nodes (fraction)", fontsize=12)
    ax.set_title("S8: Adaptive P99 Latency (ms)\nBreaking-Point Analysis", fontsize=13)

    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            val = pivot.values[i, j]
            color = "white" if val > 100 else "black"
            marker = " ✗" if val > 50 else " ✓"
            ax.text(j, i, f"{val:.0f}{marker}", ha="center", va="center",
                    fontsize=10, color=color, fontweight="bold")

    plt.colorbar(im, ax=ax, label="P99 Latency (ms)")
    fig.tight_layout()

    out_path = os.path.join(OUTPUT_DIR, "breaking_point_heatmap.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Plot saved to {out_path}")


def _plot_p99_curves(df: pd.DataFrame):
    """P99 vs fault count for each severity, adaptive only."""
    adaptive = df[df["baseline"] == "adaptive"]
    if adaptive.empty:
        return

    fig, axes = plt.subplots(1, len(SEVERITIES), figsize=(16, 5), sharey=True)
    if len(SEVERITIES) == 1:
        axes = [axes]

    colors = {3.0: "#2ca02c", 5.0: "#ff7f0e", 10.0: "#d62728", 20.0: "#9467bd"}

    for ax, sev in zip(axes, SEVERITIES):
        subset = adaptive[adaptive["slowdown"] == sev]
        for bl_name, bl_group in df[df["slowdown"] == sev].groupby("baseline"):
            color = BASELINE_COLORS.get(bl_name, "gray")
            label = BASELINE_LABELS.get(bl_name, bl_name)
            means = bl_group.groupby("n_faults")["p99_latency"].mean() * 1000
            ax.plot(means.index, means.values, "o-", color=color, label=label,
                    linewidth=2, markersize=5)

        ax.axhline(y=50, color="red", linestyle="--", alpha=0.5)
        ax.set_xlabel("Fault Nodes", fontsize=11)
        ax.set_title(f"{sev:.0f}x slowdown", fontsize=12)
        ax.grid(True, alpha=0.3)
        ax.set_xticks(FAULT_COUNTS)

    axes[0].set_ylabel("P99 Latency (ms)", fontsize=12)
    axes[-1].legend(fontsize=8, loc="upper left")
    fig.suptitle("S8: Breaking-Point Analysis (32 nodes, 80% load)", fontsize=14)
    fig.tight_layout()

    out_path = os.path.join(OUTPUT_DIR, "p99_vs_faults.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Plot saved to {out_path}")


if __name__ == "__main__":
    run_s8()
