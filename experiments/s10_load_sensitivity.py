"""S10: Load factor sensitivity — validate max_fault_fraction = 1 - L/U.

Sweep load_factor x fault_count at fixed severity (5x) to produce a
theory-vs-empirical breaking-point curve.

32 nodes, permanent faults at 5x slowdown.
- Load factors: 0.70, 0.80, 0.85, 0.90
- Fault counts: 2, 4, 6, 8 (6.25% to 25%)
- Baselines: adaptive, no_mitigation
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

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "s10_load_sensitivity")

LOAD_FACTORS = [0.70, 0.80, 0.85, 0.90]
FAULT_COUNTS = [2, 4, 6, 8]
SLOWDOWN = 5.0
N_RUNS = 10
DURATION = 60.0
WARMUP = 5.0
N_WORKERS = 32
U_THRESHOLD = 0.92  # isolation utilization ceiling

BASELINES = [
    ("adaptive", True, StrategyConfig()),
    ("no_mitigation", False, StrategyConfig()),
]


def _run_single(
    load_factor: float,
    n_faults: int,
    baseline_name: str,
    enable_mitigation: bool,
    strategy_config: StrategyConfig,
    run_id: int,
    seed: int,
) -> dict:
    from simulator.run import run_simulation

    sim_config = SimConfig(
        n_workers=N_WORKERS,
        load_factor=load_factor,
        duration=DURATION,
        warmup=WARMUP,
        seed=seed,
    )

    fault_cfg = FaultConfig(scenarios=[
        FaultScenario(
            node_indices=list(range(n_faults)),
            pattern=PermanentFault(slowdown=SLOWDOWN),
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
        "load_factor": load_factor,
        "n_faults": n_faults,
        "fault_fraction": n_faults / N_WORKERS,
        "baseline": baseline_name,
        "run_id": run_id,
        "seed": seed,
        "elapsed_sec": elapsed,
        **stats,
    }


def run_s10():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    jobs: list[dict] = []
    for lf in LOAD_FACTORS:
        for nf in FAULT_COUNTS:
            for bl_name, bl_enable, bl_cfg in BASELINES:
                for run_id in range(N_RUNS):
                    seed = abs(hash((bl_name, lf, nf, run_id))) % 100000
                    jobs.append({
                        "load_factor": lf,
                        "n_faults": nf,
                        "baseline_name": bl_name,
                        "enable_mitigation": bl_enable,
                        "strategy_config": bl_cfg,
                        "run_id": run_id,
                        "seed": seed,
                    })

    total = len(jobs)
    max_workers = max(1, (os.cpu_count() or 1) - 1)
    print(f"Running {total} jobs ({len(LOAD_FACTORS)} loads x {len(FAULT_COUNTS)} "
          f"fault counts x {len(BASELINES)} baselines x {N_RUNS} runs) "
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
                      f"nf={job['n_faults']} run {job['run_id']}: {e}")

    total_time = time.time() - t_start
    print(f"All {total} jobs completed in {total_time:.1f}s")

    df = pd.DataFrame(all_results)

    csv_path = os.path.join(OUTPUT_DIR, "raw_results.csv")
    df.to_csv(csv_path, index=False)
    print(f"\nRaw results saved to {csv_path}")

    # Summary statistics
    summary_rows = []
    for (lf, nf, bl), group in df.groupby(["load_factor", "n_faults", "baseline"]):
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
                "load_factor": lf,
                "n_faults": nf,
                "fault_fraction": nf / N_WORKERS,
                "baseline": bl,
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
        "name": "s10_load_sensitivity",
        "load_factors": LOAD_FACTORS,
        "fault_counts": FAULT_COUNTS,
        "slowdown": SLOWDOWN,
        "n_runs": N_RUNS,
        "duration": DURATION,
        "warmup": WARMUP,
        "n_workers": N_WORKERS,
        "u_threshold": U_THRESHOLD,
        "baselines": [b[0] for b in BASELINES],
        "total_wall_time_sec": total_time,
    }
    with open(os.path.join(OUTPUT_DIR, "metadata.json"), "w") as f:
        json.dump(meta, f, indent=2)

    _plot_theory_vs_empirical(summary_df)
    _plot_heatmap(summary_df)

    print("\nS10 experiment complete!")
    return df


def _plot_theory_vs_empirical(summary_df: pd.DataFrame):
    """Overlay theoretical max_fault_fraction with empirical SLO pass/fail."""
    fig, ax = plt.subplots(figsize=(9, 6))

    # Theoretical curve: max_f = 1 - L/U
    L_range = np.linspace(0.60, 0.95, 100)
    theoretical_max = 1.0 - L_range / U_THRESHOLD
    ax.plot(L_range, theoretical_max * 100, "k-", linewidth=2.5,
            label=f"Theory: $f_{{max}} = 1 - L/U$ (U={U_THRESHOLD})")
    ax.fill_between(L_range, theoretical_max * 100, 0, alpha=0.08, color="green")
    ax.fill_between(L_range, theoretical_max * 100, 60, alpha=0.08, color="red")

    # Empirical points
    adaptive_p99 = summary_df[
        (summary_df["baseline"] == "adaptive") &
        (summary_df["metric"] == "p99_latency")
    ]

    for _, row in adaptive_p99.iterrows():
        lf = row["load_factor"]
        ff = row["fault_fraction"] * 100
        p99_ms = row["mean"] * 1000
        passes = p99_ms < 50

        marker = "o" if passes else "X"
        color = "#2ca02c" if passes else "#d62728"
        size = 80 if passes else 100
        ax.scatter(lf, ff, c=color, marker=marker, s=size, zorder=5,
                   edgecolors="black", linewidth=0.5)

    # Legend entries for pass/fail
    ax.scatter([], [], c="#2ca02c", marker="o", s=80, edgecolors="black",
               linewidth=0.5, label="P99 < 50ms (SLO pass)")
    ax.scatter([], [], c="#d62728", marker="X", s=100, edgecolors="black",
               linewidth=0.5, label="P99 >= 50ms (SLO fail)")

    ax.set_xlabel("Load Factor (L)", fontsize=13)
    ax.set_ylabel("Fault Fraction (%)", fontsize=13)
    ax.set_title(f"S10: Theory vs Empirical Breaking Point\n"
                 f"(32 nodes, {SLOWDOWN:.0f}x severity, permanent faults)", fontsize=13)
    ax.set_xlim(0.65, 0.95)
    ax.set_ylim(0, 35)
    ax.legend(fontsize=10, loc="upper right")
    ax.grid(True, alpha=0.3)

    # Annotate zones
    ax.text(0.72, 5, "SAFE\nZONE", fontsize=14, color="green", alpha=0.4,
            ha="center", fontweight="bold")
    ax.text(0.88, 25, "OVERLOAD\nZONE", fontsize=14, color="red", alpha=0.4,
            ha="center", fontweight="bold")

    fig.tight_layout()
    out_path = os.path.join(OUTPUT_DIR, "theory_vs_empirical.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Plot saved to {out_path}")


def _plot_heatmap(summary_df: pd.DataFrame):
    """Heatmap: adaptive P99 across load_factor x fault_count."""
    adaptive_p99 = summary_df[
        (summary_df["baseline"] == "adaptive") &
        (summary_df["metric"] == "p99_latency")
    ]
    if adaptive_p99.empty:
        return

    pivot = adaptive_p99.pivot_table(
        index="n_faults", columns="load_factor", values="mean"
    ) * 1000  # to ms

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(pivot.values, cmap="RdYlGn_r", aspect="auto",
                   vmin=20, vmax=200)
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([f"{lf:.0%}" for lf in pivot.columns])
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([f"{nf} ({nf*100//N_WORKERS}%)" for nf in pivot.index])
    ax.set_xlabel("Load Factor", fontsize=12)
    ax.set_ylabel("Fault Nodes (fraction)", fontsize=12)
    ax.set_title(f"S10: Adaptive P99 Latency (ms)\n"
                 f"Load Sensitivity ({SLOWDOWN:.0f}x severity)", fontsize=13)

    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            val = pivot.values[i, j]
            color = "white" if val > 100 else "black"
            marker = " X" if val > 50 else " ok"
            ax.text(j, i, f"{val:.0f}{marker}", ha="center", va="center",
                    fontsize=10, color=color, fontweight="bold")

    plt.colorbar(im, ax=ax, label="P99 Latency (ms)")
    fig.tight_layout()

    out_path = os.path.join(OUTPUT_DIR, "load_heatmap.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Plot saved to {out_path}")


if __name__ == "__main__":
    run_s10()
