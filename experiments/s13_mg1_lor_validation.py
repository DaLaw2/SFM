"""S13: M/G/1 and LOR validation experiments.

Two sub-experiments:
  A) M/G/1 utilization ceiling validation:
     - Sweep service_cv in {0.0, 0.5, 1.0} (C_s^2 = {0, 0.25, 1.0})
     - For each, sweep load_factor to find the empirical U where P99 crosses SLO
     - Compare against theory: U(C_s) = alpha / (alpha + 1 + C_s^2)
  B) LOR vs P2C comparison:
     - Run S2/S4/S6-style faults under both P2C and LOR
     - Compare P99 across strategies
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
from simulator.fault import FaultScenario, PermanentFault
from experiments.runner import DEFAULT_BASELINES

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "s13_mg1_lor")
N_RUNS = 10
DURATION = 60.0
WARMUP = 10.0
N_WORKERS = 32


# --- Part A: M/G/1 utilization ceiling validation ---

SERVICE_CVS = [0.0, 0.5, 1.0]  # C_s^2 = {0, 0.25, 1.0}
LOAD_FACTORS_A = [0.70, 0.75, 0.78, 0.80, 0.82, 0.84, 0.85, 0.86, 0.87, 0.88, 0.89, 0.90]


def _run_single_a(
    service_cv: float,
    load_factor: float,
    run_id: int,
    seed: int,
) -> dict:
    """Single run for Part A: no faults, just measure P99 at given load + CV."""
    from simulator.run import run_simulation

    sim_config = SimConfig(
        n_workers=N_WORKERS,
        load_factor=load_factor,
        duration=DURATION,
        warmup=WARMUP,
        seed=seed,
        service_cv=service_cv,
    )
    t0 = time.time()
    stats = run_simulation(
        config=sim_config,
        fault_config=FaultConfig(),
        strategy_config=StrategyConfig(),
        enable_mitigation=False,
        verbose=False,
    )
    return {
        "service_cv": service_cv,
        "cv_sq": service_cv ** 2,
        "load_factor": load_factor,
        "run_id": run_id,
        "seed": seed,
        "elapsed_sec": time.time() - t0,
        **stats,
    }


def run_part_a():
    """Sweep load x CV to find empirical utilization ceiling."""
    print("=== Part A: M/G/1 Utilization Ceiling Validation ===")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    base_seed = 42
    jobs = []
    for cv in SERVICE_CVS:
        for lf in LOAD_FACTORS_A:
            for run_id in range(N_RUNS):
                jobs.append({
                    "service_cv": cv,
                    "load_factor": lf,
                    "run_id": run_id,
                    "seed": base_seed + run_id,
                })

    total = len(jobs)
    max_workers = max(1, (os.cpu_count() or 1) - 1)
    print(f"Running {total} jobs ({len(SERVICE_CVS)} CVs x {len(LOAD_FACTORS_A)} loads x {N_RUNS} runs)")

    results = []
    t_start = time.time()
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_single_a, **j): j for j in jobs}
        done = 0
        for f in as_completed(futures):
            done += 1
            try:
                results.append(f.result())
                if done % 20 == 0 or done == total:
                    print(f"  [{done}/{total}] {time.time() - t_start:.0f}s")
            except Exception as e:
                job = futures[f]
                print(f"  FAILED: cv={job['service_cv']} L={job['load_factor']}: {e}")

    print(f"Part A done in {time.time() - t_start:.1f}s")

    df = pd.DataFrame(results)
    df.to_csv(os.path.join(OUTPUT_DIR, "part_a_raw.csv"), index=False)

    # Summary: mean P99 per (cv, load)
    summary = df.groupby(["service_cv", "cv_sq", "load_factor"]).agg(
        p99_mean=("p99_latency", "mean"),
        p99_std=("p99_latency", "std"),
    ).reset_index()
    summary["p99_ms"] = summary["p99_mean"] * 1000
    summary.to_csv(os.path.join(OUTPUT_DIR, "part_a_summary.csv"), index=False)

    # Print crossing points
    slo = 50.0  # ms
    t_base = 10.0  # ms
    print("\n  Utilization ceiling comparison:")
    print(f"  {'C_s^2':>6} | {'U_theory':>8} | {'U_empirical':>11} | {'f_max_theory':>12}")
    for cv in SERVICE_CVS:
        cv_sq = cv ** 2
        alpha = 2.0 * (slo / t_base - 1.0)
        u_theory = alpha / (alpha + 1.0 + cv_sq)

        sub = summary[summary["service_cv"] == cv].sort_values("load_factor")
        # Find the load where P99 first exceeds SLO
        crossed = sub[sub["p99_ms"] > slo]
        if len(crossed) > 0:
            u_empirical = crossed.iloc[0]["load_factor"]
        else:
            u_empirical = "> " + str(LOAD_FACTORS_A[-1])

        fmax_theory = max(0, 1 - 0.80 / u_theory)
        print(f"  {cv_sq:6.2f} | {u_theory:8.3f} | {str(u_empirical):>11} | {fmax_theory:12.1%}")

    _plot_part_a(summary)
    return df


def _plot_part_a(summary: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(10, 6))
    colors = {0.0: "#2196F3", 0.5: "#FF9800", 1.0: "#F44336"}
    labels = {0.0: "M/D/1 ($C_s^2=0$)", 0.5: "M/G/1 ($C_s^2=0.25$)", 1.0: "M/M/1 ($C_s^2=1.0$)"}

    for cv in SERVICE_CVS:
        sub = summary[summary["service_cv"] == cv].sort_values("load_factor")
        ax.plot(sub["load_factor"], sub["p99_ms"], "o-",
                color=colors[cv], label=labels[cv], linewidth=2, markersize=5)

    ax.axhline(y=50, color="red", linestyle="--", alpha=0.5, label="SLO = 50ms")

    # Theory vertical lines
    t_base, slo = 10.0, 50.0
    alpha = 2.0 * (slo / t_base - 1.0)
    for cv in SERVICE_CVS:
        u = alpha / (alpha + 1.0 + cv ** 2)
        ax.axvline(x=u, color=colors[cv], linestyle=":", alpha=0.4)

    ax.set_xlabel("Load Factor", fontsize=12)
    ax.set_ylabel("System P99 Latency (ms)", fontsize=12)
    ax.set_title("M/G/1 Utilization Ceiling: Theory vs Empirical", fontsize=13)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(0, 120)
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "mg1_utilization_ceiling.png"), dpi=150)
    plt.close(fig)
    print(f"  Plot saved: mg1_utilization_ceiling.png")


# --- Part B: LOR vs P2C comparison ---

BALANCER_STRATEGIES = ["p2c", "lor"]
FAULT_CONFIGS_B = {
    "S2_progressive": lambda seed: FaultConfig(scenarios=[
        FaultScenario(node_indices=[0, 1],
                      pattern=PermanentFault(slowdown=5.0),
                      onset_time=5.0),
    ]),
    "S4_multi_node": lambda seed: FaultConfig(scenarios=[
        FaultScenario(node_indices=[0, 1, 2, 3],
                      pattern=PermanentFault(slowdown=3.0),
                      onset_time=5.0),
    ]),
    "S6_cascade": lambda seed: FaultConfig(scenarios=[
        FaultScenario(node_indices=[0],
                      pattern=PermanentFault(slowdown=5.0),
                      onset_time=5.0),
        FaultScenario(node_indices=[1],
                      pattern=PermanentFault(slowdown=5.0),
                      onset_time=20.0),
        FaultScenario(node_indices=[2],
                      pattern=PermanentFault(slowdown=3.0),
                      onset_time=35.0),
    ]),
}

# Only compare the key strategies
KEY_BASELINES = [b for b in DEFAULT_BASELINES
                 if b.name in ("no_mitigation", "fixed_isolation", "adaptive")]


def _run_single_b(
    balancer_strategy: str,
    fault_name: str,
    baseline_name: str,
    enable_mitigation: bool,
    strategy_config: StrategyConfig,
    run_id: int,
    seed: int,
) -> dict:
    from simulator.run import run_simulation

    fault_config = FAULT_CONFIGS_B[fault_name](seed)
    sim_config = SimConfig(
        n_workers=N_WORKERS,
        load_factor=0.80,
        duration=DURATION,
        warmup=WARMUP,
        seed=seed,
        balancer_strategy=balancer_strategy,
    )
    t0 = time.time()
    stats = run_simulation(
        config=sim_config,
        fault_config=fault_config,
        strategy_config=strategy_config,
        enable_mitigation=enable_mitigation,
        verbose=False,
    )
    return {
        "balancer": balancer_strategy,
        "fault": fault_name,
        "baseline": baseline_name,
        "run_id": run_id,
        "seed": seed,
        "elapsed_sec": time.time() - t0,
        **stats,
    }


def run_part_b():
    """Compare P2C vs LOR across fault scenarios."""
    print("\n=== Part B: LOR vs P2C Comparison ===")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    base_seed = 42
    jobs = []
    for bs in BALANCER_STRATEGIES:
        for fn in FAULT_CONFIGS_B:
            for bl in KEY_BASELINES:
                for run_id in range(N_RUNS):
                    jobs.append({
                        "balancer_strategy": bs,
                        "fault_name": fn,
                        "baseline_name": bl.name,
                        "enable_mitigation": bl.enable_mitigation,
                        "strategy_config": bl.strategy_config or StrategyConfig(),
                        "run_id": run_id,
                        "seed": base_seed + run_id,
                    })

    total = len(jobs)
    max_workers = max(1, (os.cpu_count() or 1) - 1)
    print(f"Running {total} jobs ({len(BALANCER_STRATEGIES)} balancers x "
          f"{len(FAULT_CONFIGS_B)} faults x {len(KEY_BASELINES)} baselines x {N_RUNS} runs)")

    results = []
    t_start = time.time()
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_single_b, **j): j for j in jobs}
        done = 0
        for f in as_completed(futures):
            done += 1
            try:
                results.append(f.result())
                if done % 10 == 0 or done == total:
                    print(f"  [{done}/{total}] {time.time() - t_start:.0f}s")
            except Exception as e:
                job = futures[f]
                print(f"  FAILED: {job['balancer_strategy']}/{job['fault_name']}/{job['baseline_name']}: {e}")

    print(f"Part B done in {time.time() - t_start:.1f}s")

    df = pd.DataFrame(results)
    df.to_csv(os.path.join(OUTPUT_DIR, "part_b_raw.csv"), index=False)

    # Summary table
    summary = df.groupby(["balancer", "fault", "baseline"]).agg(
        p99_mean=("p99_latency", "mean"),
        p99_std=("p99_latency", "std"),
    ).reset_index()
    summary["p99_ms"] = summary["p99_mean"] * 1000
    summary.to_csv(os.path.join(OUTPUT_DIR, "part_b_summary.csv"), index=False)

    print("\n  P99 Latency (ms) — P2C vs LOR:")
    print(f"  {'Fault':<16} {'Baseline':<16} {'P2C':>8} {'LOR':>8} {'Diff':>8}")
    for fn in FAULT_CONFIGS_B:
        for bl in KEY_BASELINES:
            p2c_row = summary[(summary["balancer"] == "p2c") &
                              (summary["fault"] == fn) &
                              (summary["baseline"] == bl.name)]
            lor_row = summary[(summary["balancer"] == "lor") &
                              (summary["fault"] == fn) &
                              (summary["baseline"] == bl.name)]
            if len(p2c_row) > 0 and len(lor_row) > 0:
                p2c_v = p2c_row.iloc[0]["p99_ms"]
                lor_v = lor_row.iloc[0]["p99_ms"]
                diff = lor_v - p2c_v
                print(f"  {fn:<16} {bl.name:<16} {p2c_v:8.1f} {lor_v:8.1f} {diff:+8.1f}")

    _plot_part_b(summary)
    return df


def _plot_part_b(summary: pd.DataFrame):
    faults = list(FAULT_CONFIGS_B.keys())
    baselines = [bl.name for bl in KEY_BASELINES]
    x = np.arange(len(faults))
    width = 0.15

    fig, ax = plt.subplots(figsize=(12, 6))
    colors_p2c = {"no_mitigation": "#EF9A9A", "fixed_isolation": "#90CAF9", "adaptive": "#A5D6A7"}
    colors_lor = {"no_mitigation": "#E53935", "fixed_isolation": "#1565C0", "adaptive": "#2E7D32"}

    for i, bl_name in enumerate(baselines):
        for j, balancer in enumerate(["p2c", "lor"]):
            vals = []
            for fn in faults:
                row = summary[(summary["balancer"] == balancer) &
                              (summary["fault"] == fn) &
                              (summary["baseline"] == bl_name)]
                vals.append(row.iloc[0]["p99_ms"] if len(row) > 0 else 0)
            offset = (i * 2 + j - 2.5) * width
            c = colors_p2c[bl_name] if balancer == "p2c" else colors_lor[bl_name]
            label = f"{bl_name} ({balancer.upper()})"
            ax.bar(x + offset, vals, width * 0.9, color=c, label=label)

    ax.axhline(y=50, color="red", linestyle="--", alpha=0.5, label="SLO")
    ax.set_xticks(x)
    ax.set_xticklabels([f.replace("_", "\n") for f in faults])
    ax.set_ylabel("P99 Latency (ms)", fontsize=12)
    ax.set_title("P2C vs LOR: P99 Latency Comparison", fontsize=13)
    ax.legend(fontsize=8, ncol=2)
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "p2c_vs_lor.png"), dpi=150)
    plt.close(fig)
    print(f"  Plot saved: p2c_vs_lor.png")


if __name__ == "__main__":
    run_part_a()
    run_part_b()

    meta = {
        "name": "s13_mg1_lor_validation",
        "parts": ["A: M/G/1 utilization ceiling", "B: LOR vs P2C"],
        "n_runs": N_RUNS,
        "n_workers": N_WORKERS,
    }
    with open(os.path.join(OUTPUT_DIR, "metadata.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print("\nS13 complete!")
