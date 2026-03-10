from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from simulator.control import Strategy


@dataclass
class SimulationSummary:
    total_requests: int
    throughput: float
    p50_latency: float
    p95_latency: float
    p99_latency: float
    slo_violation_rate: float
    goodput: float
    hedge_ratio: float
    strategy_transitions: int


def compute_summary(
    requests_df: pd.DataFrame,
    epochs_df: pd.DataFrame,
    duration: float,
    slo_target: float,
) -> SimulationSummary:
    valid = requests_df[~requests_df["cancelled"]]
    lats = valid["latency"].values

    total = len(valid)
    throughput = total / duration if duration > 0 else 0.0

    if len(lats) == 0:
        return SimulationSummary(
            total_requests=0, throughput=0.0,
            p50_latency=0.0, p95_latency=0.0, p99_latency=0.0,
            slo_violation_rate=0.0, goodput=0.0,
            hedge_ratio=0.0, strategy_transitions=0,
        )

    p50 = float(np.percentile(lats, 50))
    p95 = float(np.percentile(lats, 95))
    p99 = float(np.percentile(lats, 99))

    violations = (lats > slo_target).sum()
    slo_violation_rate = violations / len(lats) if len(lats) > 0 else 0.0
    goodput = (len(lats) - violations) / duration if duration > 0 else 0.0

    total_requests_incl_hedges = len(requests_df)
    hedge_count = requests_df["is_hedge"].sum()
    hedge_ratio = hedge_count / total_requests_incl_hedges if total_requests_incl_hedges > 0 else 0.0

    transitions = _count_transitions(epochs_df)

    return SimulationSummary(
        total_requests=total,
        throughput=throughput,
        p50_latency=p50,
        p95_latency=p95,
        p99_latency=p99,
        slo_violation_rate=slo_violation_rate,
        goodput=goodput,
        hedge_ratio=hedge_ratio,
        strategy_transitions=transitions,
    )


def _count_transitions(epochs_df: pd.DataFrame) -> int:
    strat_cols = [c for c in epochs_df.columns if c.startswith("strategy_")]
    count = 0
    for col in strat_cols:
        vals = epochs_df[col].values
        for i in range(1, len(vals)):
            if vals[i] != vals[i - 1]:
                count += 1
    return count


def aggregate_summaries(summaries: list[SimulationSummary]) -> dict[str, dict[str, float]]:
    if not summaries:
        return {}

    fields = [
        "throughput", "p50_latency", "p95_latency", "p99_latency",
        "slo_violation_rate", "goodput", "hedge_ratio", "strategy_transitions",
    ]
    result: dict[str, dict[str, float]] = {}
    n = len(summaries)
    z = 1.96  # 95% CI

    for f in fields:
        vals = np.array([getattr(s, f) for s in summaries])
        mean = float(vals.mean())
        std = float(vals.std(ddof=1)) if n > 1 else 0.0
        ci = z * std / np.sqrt(n) if n > 1 else 0.0
        result[f] = {"mean": mean, "std": std, "ci_95": ci, "n": n}

    return result


# ---------------------------------------------------------------------------
# Functions matching the task spec interface
# ---------------------------------------------------------------------------

def compute_stats(
    df_requests: pd.DataFrame,
    warmup: float = 10.0,
    slo_target: float = 0.05,
) -> dict[str, float]:
    """Compute summary statistics from request DataFrame.

    Returns dict with throughput, latency_p50/p95/p99, slo_violation_rate,
    goodput, and hedge_overhead.
    """
    df = df_requests[df_requests["arrival"] >= warmup].copy()
    completed = df[~df["cancelled"]]

    if completed.empty:
        return {
            "throughput": 0.0,
            "latency_p50": 0.0,
            "latency_p95": 0.0,
            "latency_p99": 0.0,
            "slo_violation_rate": 1.0,
            "goodput": 0.0,
            "hedge_overhead": 0.0,
        }

    duration = completed["end"].max() - warmup
    throughput = len(completed) / duration if duration > 0 else 0.0

    lats = completed["latency"].values
    p50 = float(np.percentile(lats, 50))
    p95 = float(np.percentile(lats, 95))
    p99 = float(np.percentile(lats, 99))

    violations = int((lats > slo_target).sum())
    slo_violation_rate = violations / len(lats)
    good = len(lats) - violations
    goodput = good / len(df) if len(df) > 0 else 0.0

    hedge_count = int(df["is_hedge"].sum())
    hedge_overhead = hedge_count / len(df) if len(df) > 0 else 0.0

    return {
        "throughput": throughput,
        "latency_p50": p50,
        "latency_p95": p95,
        "latency_p99": p99,
        "slo_violation_rate": float(slo_violation_rate),
        "goodput": float(goodput),
        "hedge_overhead": float(hedge_overhead),
    }


def compute_per_epoch_stats(df_epochs: pd.DataFrame) -> dict[str, list]:
    """Compute per-epoch summary for time series analysis."""
    if df_epochs.empty:
        return {"time": [], "system_p99": [], "slo_dist": [], "spare": []}

    result: dict[str, list] = {
        "time": df_epochs["time"].tolist(),
        "system_p99": df_epochs["system_p99"].tolist(),
        "slo_dist": df_epochs["slo_dist"].tolist(),
    }
    spare_col = "spare_capacity" if "spare_capacity" in df_epochs.columns else "spare"
    result["spare"] = df_epochs[spare_col].tolist()
    return result


def multi_run_summary(
    stats_list: list[dict[str, float]],
) -> dict[str, dict[str, float]]:
    """Compute mean and 95% CI across multiple runs using t-distribution."""
    if not stats_list:
        return {}

    keys = stats_list[0].keys()
    result: dict[str, dict[str, float]] = {}

    try:
        from scipy import stats as sp_stats
        _has_scipy = True
    except ImportError:
        _has_scipy = False

    for key in keys:
        values = np.array([s[key] for s in stats_list], dtype=float)
        n = len(values)
        mean = float(np.mean(values))

        if n < 2:
            result[key] = {"mean": mean, "ci_lo": mean, "ci_hi": mean}
            continue

        sem = float(np.std(values, ddof=1) / np.sqrt(n))
        if _has_scipy:
            t_crit = float(sp_stats.t.ppf(0.975, df=n - 1))
        else:
            # Fallback: use z=1.96 approximation for large n
            t_crit = 1.96
        margin = t_crit * sem
        result[key] = {
            "mean": mean,
            "ci_lo": mean - margin,
            "ci_hi": mean + margin,
        }

    return result
