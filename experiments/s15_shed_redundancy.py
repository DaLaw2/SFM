"""S15: SHED Redundancy Theorem validation.

Demonstrates that P2C's queue-depth tiebreaker dominates SHED's weight-based
sampling bias, making graduated response redundant under P2C routing.

Key design: includes a "weighted_random + SHED" control to prove the
redundancy is P2C-specific (SHED helps without queue-depth comparison).

  E1: Scale invariance — vary N (8,16,32,64), fixed fault 3x
      Hypothesis: SHED ~= no_mitigation under P2C at all scales
  E2: Severity sweep — vary s (1.5,2,3,5,10), N=16
      Hypothesis: SHED never meaningfully beats no_mitigation under P2C
  E3: Load sweep — vary L (0.70,0.80,0.85), N=16, 3x fault
      Hypothesis: SHED counterproductive at high load under P2C
  E4: Multi-fault — vary f (1,2,4,8) at 2x, N=32
      Hypothesis: Even many moderate faults, SHED ~= no_mitigation under P2C
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
from experiments.runner import DEFAULT_BASELINES, Baseline

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "s15_shed_redundancy")
N_RUNS = 10
DURATION = 60.0
WARMUP = 10.0

# Baselines under P2C routing
P2C_BASELINES = [b for b in DEFAULT_BASELINES
                 if b.name in ("no_mitigation", "fixed_shedding", "fixed_isolation", "adaptive")]

# Control baselines under weighted_random routing (no queue-depth comparison)
# These prove SHED's redundancy is P2C-specific
WR_BASELINES = [
    Baseline(
        name="wr_no_mitigation",
        enable_mitigation=False,
        description="Weighted random, no mitigation",
    ),
    Baseline(
        name="wr_shedding",
        enable_mitigation=True,
        strategy_config=StrategyConfig(
            theta_spec=999.0, theta_shed=0.1, theta_iso=999.0,
        ),
        description="Weighted random + SHED (no queue-depth)",
    ),
]

ALL_BASELINES = P2C_BASELINES + WR_BASELINES


def _run_single(
    experiment: str,
    config_label: str,
    n_workers: int,
    load_factor: float,
    baseline_name: str,
    enable_mitigation: bool,
    strategy_config: StrategyConfig,
    fault_config_dict: dict,
    balancer_strategy: str,
    run_id: int,
    seed: int,
    mitigation_mode: str | None = None,
) -> dict:
    from simulator.run import run_simulation
    from simulator.fault import FaultScenario, PermanentFault

    # Reconstruct FaultConfig from dict (for pickling across processes)
    scenarios = []
    for sc in fault_config_dict["scenarios"]:
        scenarios.append(FaultScenario(
            node_indices=sc["node_indices"],
            pattern=PermanentFault(slowdown=sc["slowdown"]),
            onset_time=sc["onset_time"],
        ))
    fault_config = FaultConfig(scenarios=scenarios)

    sim_config = SimConfig(
        n_workers=n_workers,
        load_factor=load_factor,
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
        mitigation_mode=mitigation_mode,
    )
    return {
        "experiment": experiment,
        "config_label": config_label,
        "n_workers": n_workers,
        "load_factor": load_factor,
        "baseline": baseline_name,
        "balancer": balancer_strategy,
        "run_id": run_id,
        "seed": seed,
        "elapsed_sec": time.time() - t0,
        **stats,
    }


def _fault_dict(node_indices, slowdown, onset=10.0):
    """Create serializable fault config dict."""
    return {"scenarios": [{"node_indices": node_indices, "slowdown": slowdown, "onset_time": onset}]}


# Experiment definitions
EXPERIMENTS = {
    "E1_scale_invariance": {
        "description": "Vary N (8,16,32,64), 1 fault at 3x, L=0.70",
        "configs": [
            {"label": f"N={n}", "n_workers": n, "load_factor": 0.70, "fault": _fault_dict([0], 3.0)}
            for n in [8, 16, 32, 64]
        ],
    },
    "E2_severity_sweep": {
        "description": "Vary severity (1.5,2,3,5,10), N=16, 1 fault, L=0.70",
        "configs": [
            {"label": f"s={s}", "n_workers": 16, "load_factor": 0.70, "fault": _fault_dict([0], s)}
            for s in [1.5, 2.0, 3.0, 5.0, 10.0]
        ],
    },
    "E3_load_sweep": {
        "description": "Vary L (0.70,0.80,0.85), N=16, 1 fault at 3x",
        "configs": [
            {"label": f"L={lf}", "n_workers": 16, "load_factor": lf, "fault": _fault_dict([0], 3.0)}
            for lf in [0.70, 0.80, 0.85]
        ],
    },
    "E4_multi_fault": {
        "description": "Vary f (1,2,4,8) at 2x, N=32, L=0.70",
        "configs": [
            {"label": f"f={f}", "n_workers": 32, "load_factor": 0.70, "fault": _fault_dict(list(range(f)), 2.0)}
            for f in [1, 2, 4, 8]
        ],
    },
}

# E2 also runs under weighted_random to show SHED helps without P2C
WR_EXPERIMENT = "E2_severity_sweep"


def run_s15():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    base_seed = 42

    jobs = []
    # P2C baselines across all experiments
    for exp_name, exp_cfg in EXPERIMENTS.items():
        for cfg in exp_cfg["configs"]:
            for bl in P2C_BASELINES:
                for run_id in range(N_RUNS):
                    jobs.append({
                        "experiment": exp_name,
                        "config_label": cfg["label"],
                        "n_workers": cfg["n_workers"],
                        "load_factor": cfg["load_factor"],
                        "baseline_name": bl.name,
                        "enable_mitigation": bl.enable_mitigation,
                        "strategy_config": bl.strategy_config or StrategyConfig(),
                        "fault_config_dict": cfg["fault"],
                        "balancer_strategy": "p2c",
                        "run_id": run_id,
                        "seed": base_seed + run_id,
                        "mitigation_mode": bl.mitigation_mode,
                    })

    # Weighted-random control: E2 only (sufficient to prove P2C-specificity)
    for cfg in EXPERIMENTS[WR_EXPERIMENT]["configs"]:
        for bl in WR_BASELINES:
            for run_id in range(N_RUNS):
                jobs.append({
                    "experiment": "E2_wr_control",
                    "config_label": cfg["label"],
                    "n_workers": cfg["n_workers"],
                    "load_factor": cfg["load_factor"],
                    "baseline_name": bl.name,
                    "enable_mitigation": bl.enable_mitigation,
                    "strategy_config": bl.strategy_config or StrategyConfig(),
                    "fault_config_dict": cfg["fault"],
                    "balancer_strategy": "weighted_random",
                    "run_id": run_id,
                    "seed": base_seed + run_id,
                    "mitigation_mode": bl.mitigation_mode,
                })

    total = len(jobs)
    max_workers = max(1, (os.cpu_count() or 1) - 1)
    print(f"S15 SHED Redundancy: {total} jobs ({len(EXPERIMENTS)} experiments + WR control)")
    print(f"  Workers: {max_workers}, Runs per config: {N_RUNS}")

    results = []
    t_start = time.time()
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_single, **j): j for j in jobs}
        done = 0
        for f in as_completed(futures):
            done += 1
            try:
                results.append(f.result())
                if done % 40 == 0 or done == total:
                    print(f"  [{done}/{total}] {time.time() - t_start:.0f}s")
            except Exception as e:
                job = futures[f]
                print(f"  FAILED: {job['experiment']}/{job['baseline_name']} "
                      f"N={job['n_workers']} L={job['load_factor']}: {e}")

    elapsed = time.time() - t_start
    print(f"All done in {elapsed:.1f}s")

    df = pd.DataFrame(results)
    df.to_csv(os.path.join(OUTPUT_DIR, "raw_results.csv"), index=False)

    # Analysis per experiment
    _analyze_e1(df)
    _analyze_e2(df)
    _analyze_e3(df)
    _analyze_e4(df)
    _analyze_wr_control(df)

    # Summary CSV (include config_label for proper per-config aggregation)
    summary = df.groupby(["experiment", "config_label", "baseline"]).agg(
        p99_mean=("p99_latency", "mean"),
        p99_std=("p99_latency", "std"),
        p999_mean=("p999_latency", "mean"),
        slo_viol=("slo_violation_rate", "mean"),
        throughput=("throughput", "mean"),
    ).reset_index()
    summary["p99_ms"] = summary["p99_mean"] * 1000
    summary.to_csv(os.path.join(OUTPUT_DIR, "summary.csv"), index=False)

    # Overall SHED redundancy summary
    _analyze_shed_effectiveness(df)

    # Plots
    _plot_e1(df)
    _plot_e2_severity(df)
    _plot_wr_comparison(df)

    meta = {
        "name": "s15_shed_redundancy",
        "description": "SHED Redundancy Theorem validation",
        "experiments": {k: v["description"] for k, v in EXPERIMENTS.items()},
        "n_runs": N_RUNS,
        "duration": DURATION,
        "baselines_p2c": [b.name for b in P2C_BASELINES],
        "baselines_wr": [b.name for b in WR_BASELINES],
    }
    with open(os.path.join(OUTPUT_DIR, "metadata.json"), "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nS15 complete! Results in {OUTPUT_DIR}")
    return df


def _print_table(df_exp, group_col, baselines=None):
    """Print P99 table grouped by config_label. Returns per-config deltas."""
    if baselines is None:
        baselines = ["no_mitigation", "fixed_shedding", "fixed_isolation", "adaptive"]
    bl_short = [b[:8] for b in baselines]
    header = "  " + f"{'config':>8}" + "".join(f"  {s:>8}" for s in bl_short)
    if len(baselines) >= 2:
        header += f"  {'D(1-0)':>8}"
    print(f"\n{header}")

    rows = []
    for label, grp in df_exp.groupby(group_col, sort=False):
        vals = {}
        for bl in baselines:
            sub = grp[grp["baseline"] == bl]
            vals[bl] = sub["p99_latency"].mean() * 1000 if len(sub) > 0 else float("nan")

        line = f"  {str(label):>8}"
        for bl in baselines:
            line += f"  {vals[bl]:8.1f}"

        # Delta: second baseline minus first (SHED effect)
        if len(baselines) >= 2:
            delta = vals[baselines[1]] - vals[baselines[0]]
            line += f"  {delta:+8.1f}"
            rows.append({"label": label, "delta": delta,
                         **{bl: vals[bl] for bl in baselines}})
        print(line)

    return rows


def _analyze_e1(df):
    """E1: Scale invariance — SHED effectiveness vs N."""
    e1 = df[df["experiment"] == "E1_scale_invariance"]
    if e1.empty:
        return
    print(f"\n{'='*70}")
    print("E1: Scale Invariance (1 fault at 3x, L=0.70)")
    print(f"{'='*70}")

    rows = _print_table(e1, "config_label",
                        ["no_mitigation", "fixed_shedding", "fixed_isolation", "adaptive"])
    shed_deltas = [r["delta"] for r in rows]
    avg = np.mean(shed_deltas)
    print(f"\n  SHED D across scales: {[f'{d:+.1f}' for d in shed_deltas]}")
    print(f"  Mean SHED D: {avg:+.1f}ms")


def _analyze_e2(df):
    """E2: Severity sweep — SHED effectiveness vs severity."""
    e2 = df[df["experiment"] == "E2_severity_sweep"]
    if e2.empty:
        return
    print(f"\n{'='*70}")
    print("E2: Severity Sweep (N=16, L=0.70, under P2C)")
    print(f"{'='*70}")

    rows = _print_table(e2, "config_label",
                        ["no_mitigation", "fixed_shedding", "fixed_isolation", "adaptive"])
    shed_deltas = [r["delta"] for r in rows]
    print(f"\n  SHED D across severities: {[f'{d:+.1f}' for d in shed_deltas]}")


def _analyze_e3(df):
    """E3: Load sweep — SHED effectiveness vs load."""
    e3 = df[df["experiment"] == "E3_load_sweep"]
    if e3.empty:
        return
    print(f"\n{'='*70}")
    print("E3: Load Sweep (N=16, 1 fault at 3x)")
    print(f"{'='*70}")

    rows = _print_table(e3, "config_label",
                        ["no_mitigation", "fixed_shedding", "fixed_isolation", "adaptive"])
    shed_deltas = [r["delta"] for r in rows]
    print(f"\n  SHED D across loads: {[f'{d:+.1f}' for d in shed_deltas]}")


def _analyze_e4(df):
    """E4: Multi-fault — SHED effectiveness vs fault count."""
    e4 = df[df["experiment"] == "E4_multi_fault"]
    if e4.empty:
        return
    print(f"\n{'='*70}")
    print("E4: Multi-Fault (N=32, 2x slowdown, L=0.70)")
    print(f"{'='*70}")

    rows = _print_table(e4, "config_label",
                        ["no_mitigation", "fixed_shedding", "fixed_isolation", "adaptive"])
    shed_deltas = [r["delta"] for r in rows]
    print(f"\n  SHED D across fault counts: {[f'{d:+.1f}' for d in shed_deltas]}")


def _analyze_wr_control(df):
    """Weighted-random control: SHED should help WITHOUT P2C."""
    wr = df[df["experiment"] == "E2_wr_control"]
    if wr.empty:
        return
    print(f"\n{'='*70}")
    print("WR Control: Severity Sweep under Weighted Random (no queue-depth)")
    print(f"{'='*70}")

    rows = _print_table(wr, "config_label",
                        ["wr_no_mitigation", "wr_shedding"])
    shed_deltas = [r["delta"] for r in rows]
    avg = np.mean(shed_deltas)
    print(f"\n  SHED D under weighted_random: {[f'{d:+.1f}' for d in shed_deltas]}")
    print(f"  Mean SHED D: {avg:+.1f}ms")
    if avg < -2:
        print(f"  -> SHED helps significantly without P2C ({avg:+.1f}ms)")
        print(f"  -> Confirms redundancy is P2C-specific")
    else:
        print(f"  -> SHED does not help even without P2C")


def _analyze_shed_effectiveness(df):
    """Overall SHED effectiveness analysis across all experiments."""
    print(f"\n{'='*70}")
    print("SHED REDUNDANCY SUMMARY")
    print(f"{'='*70}")

    print(f"\n  Under P2C routing:")
    for exp_name in EXPERIMENTS:
        exp_df = df[df["experiment"] == exp_name]
        for label, grp in exp_df.groupby("config_label", sort=False):
            nomit = grp[grp["baseline"] == "no_mitigation"]["p99_latency"].mean() * 1000
            shed = grp[grp["baseline"] == "fixed_shedding"]["p99_latency"].mean() * 1000
            iso = grp[grp["baseline"] == "fixed_isolation"]["p99_latency"].mean() * 1000
            shed_d = shed - nomit
            iso_d = iso - nomit
            print(f"    {exp_name[:12]:<12s} {label:>6s}  "
                  f"SHED D={shed_d:+5.1f}ms  ISO D={iso_d:+6.1f}ms")

    # WR control summary
    wr = df[df["experiment"] == "E2_wr_control"]
    if not wr.empty:
        print(f"\n  Under Weighted Random routing (no queue-depth):")
        for label, grp in wr.groupby("config_label", sort=False):
            nomit = grp[grp["baseline"] == "wr_no_mitigation"]["p99_latency"].mean() * 1000
            shed = grp[grp["baseline"] == "wr_shedding"]["p99_latency"].mean() * 1000
            shed_d = shed - nomit
            print(f"    E2_wr       {label:>6s}  SHED D={shed_d:+5.1f}ms")

    print(f"\n  SHED delta ~ 0 under P2C but delta < 0 under WR -> P2C subsumes SHED")
    print(f"  SHED delta > 0 under P2C -> SHED counterproductive (detection overhead)")


def _plot_e1(df):
    """Plot E1: P99 vs cluster size for each baseline."""
    e1 = df[df["experiment"] == "E1_scale_invariance"]
    if e1.empty:
        return

    fig, ax = plt.subplots(figsize=(8, 5))
    for bl in P2C_BASELINES:
        sub = e1[e1["baseline"] == bl.name]
        means = sub.groupby("n_workers")["p99_latency"].mean() * 1000
        stds = sub.groupby("n_workers")["p99_latency"].std() * 1000
        ax.errorbar(means.index, means.values, yerr=stds.values,
                    label=bl.name, marker="o", capsize=3)

    ax.set_xlabel("Cluster Size (N)")
    ax.set_ylabel("P99 Latency (ms)")
    ax.set_title("E1: SHED vs Baselines at Different Scales\n(1 fault at 3x, L=0.70)")
    ax.legend()
    ax.set_xscale("log", base=2)
    ax.set_xticks([8, 16, 32, 64])
    ax.get_xaxis().set_major_formatter(plt.ScalarFormatter())
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "e1_scale_invariance.png"), dpi=150)
    plt.close(fig)


def _plot_e2_severity(df):
    """Plot E2: P99 vs severity for each baseline (per config_label)."""
    e2 = df[df["experiment"] == "E2_severity_sweep"]
    if e2.empty:
        return

    severities = [1.5, 2.0, 3.0, 5.0, 10.0]
    labels = [f"s={s}" for s in severities]

    fig, ax = plt.subplots(figsize=(8, 5))
    for bl in P2C_BASELINES:
        sub = e2[e2["baseline"] == bl.name]
        p99_vals = []
        for label in labels:
            val = sub[sub["config_label"] == label]["p99_latency"].mean() * 1000
            p99_vals.append(val)
        ax.plot(severities, p99_vals, label=bl.name, marker="o")

    ax.set_xlabel("Slowdown Factor (s)")
    ax.set_ylabel("P99 Latency (ms)")
    ax.set_title("E2: P99 vs Severity under P2C\n(N=16, L=0.70)")
    ax.legend()
    ax.set_xscale("log")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "e2_severity_sweep.png"), dpi=150)
    plt.close(fig)


def _plot_wr_comparison(df):
    """Plot: SHED delta under P2C vs Weighted Random."""
    e2_p2c = df[df["experiment"] == "E2_severity_sweep"]
    e2_wr = df[df["experiment"] == "E2_wr_control"]
    if e2_p2c.empty or e2_wr.empty:
        return

    severities = [1.5, 2.0, 3.0, 5.0, 10.0]
    labels = [f"s={s}" for s in severities]

    p2c_deltas = []
    wr_deltas = []
    for label in labels:
        # P2C delta
        p2c_grp = e2_p2c[e2_p2c["config_label"] == label]
        nomit = p2c_grp[p2c_grp["baseline"] == "no_mitigation"]["p99_latency"].mean() * 1000
        shed = p2c_grp[p2c_grp["baseline"] == "fixed_shedding"]["p99_latency"].mean() * 1000
        p2c_deltas.append(shed - nomit)

        # WR delta
        wr_grp = e2_wr[e2_wr["config_label"] == label]
        nomit_wr = wr_grp[wr_grp["baseline"] == "wr_no_mitigation"]["p99_latency"].mean() * 1000
        shed_wr = wr_grp[wr_grp["baseline"] == "wr_shedding"]["p99_latency"].mean() * 1000
        wr_deltas.append(shed_wr - nomit_wr)

    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(severities))
    w = 0.35
    ax.bar(x - w/2, p2c_deltas, w, label="SHED delta (P2C)", color="steelblue")
    ax.bar(x + w/2, wr_deltas, w, label="SHED delta (Weighted Random)", color="coral")
    ax.axhline(y=0, color="black", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels([str(s) for s in severities])
    ax.set_xlabel("Slowdown Factor (s)")
    ax.set_ylabel("SHED P99 Delta (ms)")
    ax.set_title("SHED Effect: P2C vs Weighted Random\n(negative = SHED helps)")
    ax.legend()
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "shed_p2c_vs_wr.png"), dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    run_s15()
