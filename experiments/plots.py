"""Plotting utilities for experiment results."""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


BASELINE_COLORS = {
    "no_mitigation": "#d62728",
    "fixed_speculation": "#ff7f0e",
    "fixed_shedding": "#2ca02c",
    "fixed_isolation": "#9467bd",
    "adaptive": "#1f77b4",
}

BASELINE_LABELS = {
    "no_mitigation": "No Mitigation",
    "fixed_speculation": "Fixed Speculation",
    "fixed_shedding": "Fixed Shedding",
    "fixed_isolation": "Fixed Isolation",
    "adaptive": "Adaptive (Ours)",
}


def plot_comparison_bar(
    summary_df: pd.DataFrame,
    metric: str,
    output_path: str,
    title: str = "",
    ylabel: str = "",
    multiply: float = 1.0,
    slo_line: float | None = None,
):
    """Bar chart comparing baselines for a single metric."""
    if not HAS_MPL:
        print("matplotlib not available; skipping plot")
        return

    sub = summary_df[summary_df["metric"] == metric].copy()
    sub = sub.sort_values("baseline", key=lambda x: x.map(
        {k: i for i, k in enumerate(BASELINE_COLORS.keys())}
    ))

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(sub))
    colors = [BASELINE_COLORS.get(b, "gray") for b in sub["baseline"]]
    labels = [BASELINE_LABELS.get(b, b) for b in sub["baseline"]]

    bars = ax.bar(x, sub["mean"] * multiply, yerr=sub["ci_95"] * multiply,
                  color=colors, capsize=5, alpha=0.85, edgecolor="black", linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_ylabel(ylabel or metric, fontsize=12)
    ax.set_title(title or f"{metric} by Baseline", fontsize=13)

    if slo_line is not None:
        ax.axhline(y=slo_line, color="red", linestyle="--", alpha=0.7, label=f"SLO = {slo_line:.0f}ms")
        ax.legend()

    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"Plot saved to {output_path}")


def plot_severity_sweep(
    raw_df: pd.DataFrame,
    x_col: str,
    output_path: str,
    title: str = "",
    xlabel: str = "",
):
    """Line plot: P99 latency across varying severity for each baseline."""
    if not HAS_MPL:
        return

    fig, ax = plt.subplots(figsize=(10, 6))

    for bl_name, group in raw_df.groupby("baseline"):
        color = BASELINE_COLORS.get(bl_name, "gray")
        label = BASELINE_LABELS.get(bl_name, bl_name)
        means = group.groupby(x_col)["p99_latency"].mean() * 1000
        ax.plot(means.index, means.values, "o-", color=color, label=label, linewidth=2, markersize=4)

    ax.axhline(y=50, color="red", linestyle="--", alpha=0.5, label="SLO = 50ms")
    ax.set_xlabel(xlabel or x_col, fontsize=12)
    ax.set_ylabel("System P99 Latency (ms)", fontsize=12)
    ax.set_title(title, fontsize=13)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"Plot saved to {output_path}")


def plot_timeline(
    epochs_df: pd.DataFrame,
    output_path: str,
    title: str = "",
):
    """Time series plot of system P99, strategies, and severities."""
    if not HAS_MPL:
        return

    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)

    # P99 over time
    ax = axes[0]
    ax.plot(epochs_df["time"], epochs_df["system_p99"] * 1000, color="#1f77b4", linewidth=1)
    ax.axhline(y=50, color="red", linestyle="--", alpha=0.5)
    ax.set_ylabel("P99 Latency (ms)")
    ax.set_title(title or "System Timeline")
    ax.grid(True, alpha=0.3)

    # Severities over time (if available as columns)
    ax = axes[1]
    if "severities" in epochs_df.columns:
        sev_data = epochs_df["severities"].apply(
            lambda x: max(x.values()) if isinstance(x, dict) and x else 0
        )
        ax.plot(epochs_df["time"], sev_data, color="#d62728", linewidth=1)
    ax.set_ylabel("Max Severity")
    ax.grid(True, alpha=0.3)

    # Spare capacity
    ax = axes[2]
    if "spare_capacity" in epochs_df.columns:
        ax.plot(epochs_df["time"], epochs_df["spare_capacity"], color="#2ca02c", linewidth=1)
    ax.set_ylabel("Spare Capacity")
    ax.set_xlabel("Time (s)")
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"Plot saved to {output_path}")


def generate_all_plots(output_dir: str):
    """Generate standard plots from an experiment's output directory."""
    summary_path = os.path.join(output_dir, "summary.csv")
    if not os.path.exists(summary_path):
        print(f"No summary.csv found in {output_dir}")
        return

    summary = pd.read_csv(summary_path)

    # P99 latency comparison
    plot_comparison_bar(
        summary, "p99_latency",
        os.path.join(output_dir, "p99_comparison.png"),
        title="P99 Latency by Strategy",
        ylabel="P99 Latency (ms)",
        multiply=1000,
        slo_line=50,
    )

    # Throughput comparison
    plot_comparison_bar(
        summary, "throughput",
        os.path.join(output_dir, "throughput_comparison.png"),
        title="Throughput by Strategy",
        ylabel="Throughput (req/s)",
    )
