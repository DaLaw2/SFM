"""Experiment runner with multiprocessing parallelism.

Usage:
    from experiments.runner import ExperimentRunner, Baseline
    runner = ExperimentRunner(name="scenario_1", output_dir="experiments/results/scenario_1")
    runner.run_all(fault_config_fn=..., baselines=DEFAULT_BASELINES, n_runs=10, duration=60)
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from simulator.config import SimConfig, FaultConfig, StrategyConfig
from simulator.fault import FaultScenario, PermanentFault


@dataclass
class Baseline:
    """A baseline configuration to compare against."""
    name: str
    enable_mitigation: bool
    strategy_config: StrategyConfig | None = None
    description: str = ""
    mitigation_mode: str | None = None  # "hedged", "blacklist", "retry"


# Default baselines matching the evaluation plan
DEFAULT_BASELINES: list[Baseline] = [
    Baseline(
        name="no_mitigation",
        enable_mitigation=False,
        description="No response to slow faults (lower bound)",
    ),
    Baseline(
        name="fixed_speculation",
        enable_mitigation=True,
        strategy_config=StrategyConfig(
            theta_spec=0.1, theta_shed=999.0, theta_iso=999.0,
        ),
        description="Always speculate, never shed or isolate",
    ),
    Baseline(
        name="fixed_shedding",
        enable_mitigation=True,
        strategy_config=StrategyConfig(
            theta_spec=999.0, theta_shed=0.1, theta_iso=999.0,
        ),
        description="Always shed load, never speculate or isolate",
    ),
    Baseline(
        name="fixed_isolation",
        enable_mitigation=True,
        strategy_config=StrategyConfig(
            theta_spec=999.0, theta_shed=999.0, theta_iso=0.3,
        ),
        description="Aggressively isolate slow nodes (IASO-style)",
    ),
    Baseline(
        name="adaptive",
        enable_mitigation=True,
        strategy_config=StrategyConfig(),
        description="Our adaptive multi-strategy framework",
    ),
]

# Literature baselines for comparison (Dean & Barroso 2013, Cassandra, etc.)
LITERATURE_BASELINES: list[Baseline] = [
    Baseline(
        name="lit_hedged",
        enable_mitigation=False,
        mitigation_mode="hedged",
        description="Unconditional hedged requests (Dean & Barroso 2013), delay=2*t_base",
    ),
    Baseline(
        name="lit_blacklist",
        enable_mitigation=False,
        mitigation_mode="blacklist",
        description="Outlier blacklisting (Cassandra dynamic snitch style), k=2.0",
    ),
    Baseline(
        name="lit_retry",
        enable_mitigation=False,
        mitigation_mode="retry",
        description="Timeout retry, deadline=SLO/2 then retry on another node",
    ),
]

# All baselines combined
ALL_BASELINES: list[Baseline] = DEFAULT_BASELINES + LITERATURE_BASELINES


def _run_single(
    sim_config: SimConfig,
    fault_config: FaultConfig,
    strategy_config: StrategyConfig,
    enable_mitigation: bool,
    load_schedule: list[tuple[float, float]] | None,
    baseline_name: str,
    run_id: int,
    seed: int,
    mitigation_mode: str | None = None,
) -> dict:
    """Run a single simulation. Top-level function for multiprocessing."""
    from simulator.run import run_simulation

    # Create a fresh config with the correct seed instead of mutating
    sim_config = SimConfig(
        n_workers=sim_config.n_workers,
        capacity_per_worker=sim_config.capacity_per_worker,
        t_base=sim_config.t_base,
        slo_target=sim_config.slo_target,
        slo_percentile=sim_config.slo_percentile,
        duration=sim_config.duration,
        warmup=sim_config.warmup,
        load_factor=sim_config.load_factor,
        decision_epoch=sim_config.decision_epoch,
        seed=seed,
        service_cv=sim_config.service_cv,
        balancer_strategy=sim_config.balancer_strategy,
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
        "baseline": baseline_name,
        "run_id": run_id,
        "seed": seed,
        "elapsed_sec": elapsed,
        **stats,
    }


class ExperimentRunner:
    """Run a scenario across all baselines with multiple seeds, in parallel."""

    def __init__(self, name: str, output_dir: str, max_workers: int | None = None):
        self.name = name
        self.output_dir = output_dir
        self.max_workers = max_workers or max(1, (os.cpu_count() or 1) - 1)
        os.makedirs(output_dir, exist_ok=True)

    def run_all(
        self,
        fault_config_fn: Callable[[int], FaultConfig],
        sim_config: SimConfig | None = None,
        baselines: list[Baseline] | None = None,
        n_runs: int = 10,
        duration: float = 60.0,
        warmup: float = 10.0,
        load_schedule: list[tuple[float, float]] | None = None,
    ) -> pd.DataFrame:
        if baselines is None:
            baselines = DEFAULT_BASELINES
        if sim_config is None:
            sim_config = SimConfig()

        sim_config.duration = duration
        sim_config.warmup = warmup

        # Build all jobs — use the same seed for each run_id across baselines
        # so that comparisons are paired (same arrival process).
        base_seed = sim_config.seed
        jobs: list[dict] = []
        for bl in baselines:
            for run_id in range(n_runs):
                seed = base_seed + run_id
                jobs.append({
                    "sim_config": SimConfig(
                        n_workers=sim_config.n_workers,
                        capacity_per_worker=sim_config.capacity_per_worker,
                        t_base=sim_config.t_base,
                        slo_target=sim_config.slo_target,
                        slo_percentile=sim_config.slo_percentile,
                        duration=duration,
                        warmup=warmup,
                        load_factor=sim_config.load_factor,
                        decision_epoch=sim_config.decision_epoch,
                        seed=seed,
                        service_cv=sim_config.service_cv,
                        balancer_strategy=sim_config.balancer_strategy,
                    ),
                    "fault_config": fault_config_fn(seed),
                    "strategy_config": bl.strategy_config or StrategyConfig(),
                    "enable_mitigation": bl.enable_mitigation,
                    "load_schedule": load_schedule,
                    "baseline_name": bl.name,
                    "run_id": run_id,
                    "seed": seed,
                    "mitigation_mode": bl.mitigation_mode,
                })

        total = len(jobs)
        print(f"Running {total} jobs ({len(baselines)} baselines x {n_runs} runs) "
              f"with up to {self.max_workers or os.cpu_count()} workers...")

        all_results: list[dict] = []
        t_start = time.time()

        use_sequential = os.environ.get("EXPERIMENT_SEQUENTIAL", "0") == "1"

        if use_sequential:
            done_count = 0
            for job in jobs:
                done_count += 1
                try:
                    result = _run_single(**job)
                    all_results.append(result)
                    if done_count % 10 == 0 or done_count == total:
                        elapsed = time.time() - t_start
                        print(f"  [{done_count}/{total}] {elapsed:.0f}s elapsed")
                except Exception as e:
                    print(f"  FAILED: {job['baseline_name']} run {job['run_id']}: {e}")
        else:
            with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
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
                        if done_count % 10 == 0 or done_count == total:
                            elapsed = time.time() - t_start
                            print(f"  [{done_count}/{total}] {elapsed:.0f}s elapsed")
                    except Exception as e:
                        job = futures[future]
                        print(f"  FAILED: {job['baseline_name']} run {job['run_id']}: {e}")

        total_time = time.time() - t_start
        print(f"All {total} jobs completed in {total_time:.1f}s")

        df = pd.DataFrame(all_results)

        # Save raw results
        csv_path = os.path.join(self.output_dir, "raw_results.csv")
        df.to_csv(csv_path, index=False)
        print(f"Raw results saved to {csv_path}")

        # Compute and save summary
        summary = self._compute_summary(df)
        summary_path = os.path.join(self.output_dir, "summary.csv")
        summary.to_csv(summary_path, index=False)
        print(f"Summary saved to {summary_path}")

        # Save experiment metadata
        meta = {
            "name": self.name,
            "n_runs": n_runs,
            "duration": duration,
            "warmup": warmup,
            "n_workers": sim_config.n_workers,
            "load_factor": sim_config.load_factor,
            "slo_target_ms": sim_config.slo_target * 1000,
            "baselines": [{"name": b.name, "description": b.description} for b in baselines],
            "parallelism": self.max_workers or os.cpu_count(),
            "total_wall_time_sec": total_time,
        }
        meta_path = os.path.join(self.output_dir, "metadata.json")
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

        return df

    def _compute_summary(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute mean and 95% CI for each baseline."""
        try:
            from scipy import stats as sp_stats
            def ci_fn(values, n):
                se = values.std(ddof=1) / np.sqrt(n)
                return sp_stats.t.ppf(0.975, n - 1) * se
        except ImportError:
            def ci_fn(values, n):
                se = values.std(ddof=1) / np.sqrt(n)
                return 1.96 * se

        rows = []
        for bl_name, group in df.groupby("baseline"):
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
                ci = ci_fn(values, n) if n > 1 else 0.0
                rows.append({
                    "baseline": bl_name,
                    "metric": metric,
                    "mean": mean,
                    "ci_95": ci,
                    "min": values.min(),
                    "max": values.max(),
                    "n": n,
                })

        return pd.DataFrame(rows)
