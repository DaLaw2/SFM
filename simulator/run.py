from __future__ import annotations

import argparse
import os

import numpy as np
import simpy

from simulator.config import SimConfig, FaultConfig, StrategyConfig
from simulator.core.balancer import LoadBalancer
from simulator.core.generator import RequestGenerator
from simulator.core.worker import WorkerNode
from simulator.core.speculation import SpeculationManager
from simulator.core.recovery import RecoveryProber
from simulator.control import Strategy
from simulator.control.monitor import Monitor
from simulator.control.detector import Detector
from simulator.control.selector import StrategySelector
from simulator.control.aimd import AIMDController, AIMDConfig
from simulator.fault import FaultScenario, PermanentFault
from simulator.fault.injector import FaultInjector
from simulator.metrics.collector import MetricsCollector


def run_simulation(
    config: SimConfig | None = None,
    fault_config: FaultConfig | None = None,
    strategy_config: StrategyConfig | None = None,
    enable_mitigation: bool = False,
    verbose: bool = True,
    load_schedule: list[tuple[float, float]] | None = None,
    mitigation_mode: str | None = None,
) -> dict:
    if config is None:
        config = SimConfig()
    if fault_config is None:
        fault_config = FaultConfig()
    if strategy_config is None:
        strategy_config = StrategyConfig()

    rng = np.random.default_rng(config.seed)
    env = simpy.Environment()

    # Per-worker RNG for M/G/1 service time sampling
    worker_rngs = [rng.spawn(1)[0] for _ in range(config.n_workers)]
    workers = [WorkerNode(env, i, config, rng=worker_rngs[i]) for i in range(config.n_workers)]
    balancer = LoadBalancer(workers, rng, strategy=config.balancer_strategy)
    collector = MetricsCollector()

    # Fault injection
    injector = FaultInjector(
        env, workers, fault_config.scenarios, fault_config.update_interval
    )

    # Control plane
    monitor = Monitor(env, config, workers)
    detector = Detector(t_base=config.t_base)
    node_ids = list(range(config.n_workers))
    selector = StrategySelector(node_ids, strategy_config)
    aimd = AIMDController(config.n_workers, AIMDConfig(
        alpha=strategy_config.aimd_alpha,
        beta=strategy_config.aimd_beta,
        w_min=strategy_config.w_min,
    ))
    speculation = SpeculationManager(env, config, balancer, workers)
    recovery = RecoveryProber(env, config, workers)

    # Literature baseline modes
    lit_speculation = None
    if mitigation_mode == "hedged":
        lit_speculation = SpeculationManager(
            env, config, balancer, workers,
            unconditional=True,
            hedge_delay_override=3.0 * config.t_base,  # ~healthy P99
        )
    elif mitigation_mode == "retry":
        lit_speculation = SpeculationManager(
            env, config, balancer, workers,
            unconditional=True,
            hedge_delay_override=0.7 * config.slo_target,  # 70% of SLO
        )

    # Determine which speculation manager the generator uses
    if lit_speculation is not None:
        gen_speculation = lit_speculation
    elif enable_mitigation:
        gen_speculation = speculation
    else:
        gen_speculation = None

    generator = RequestGenerator(env, config, balancer, rng, load_schedule=load_schedule,
                                  speculation=gen_speculation)

    # Start processes
    generator.run()
    env.process(injector.run())
    monitor.run()

    if mitigation_mode == "blacklist":
        from simulator.baselines.blacklist import OutlierBlacklist
        blacklist = OutlierBlacklist(
            env, monitor, balancer,
            epoch=config.decision_epoch,
            k_threshold=2.0,
            cooldown_epochs=3,
        )
        blacklist.run()
    elif enable_mitigation and mitigation_mode is None:
        recovery.run()
        env.process(_control_loop(
            env, config, monitor, detector, selector, aimd,
            balancer, speculation, recovery, collector,
        ))

    env.run(until=config.duration)

    # Collect results (exclude probes and cancelled)
    completed = [
        r for r in generator.all_requests
        if r.end_time > 0 and r.arrival_time >= config.warmup
        and not r.cancelled and not r.is_probe
    ]

    if not completed:
        if verbose:
            print("No completed requests after warmup period.")
        return {
            "total": 0, "avg_latency": 0, "p50_latency": 0,
            "p95_latency": 0, "p99_latency": 0, "p999_latency": 0,
            "max_latency": 0, "tail_ratio": 0, "throughput": 0,
            "goodput": 0, "slo_violation_rate": 0, "hedge_count": 0,
            "affected_ratio": 0,
        }

    latencies = np.array([r.latency for r in completed])
    effective_duration = config.duration - config.warmup

    p50 = float(np.percentile(latencies, 50))
    p99 = float(np.percentile(latencies, 99))

    # Identify fault node IDs from config
    fault_node_ids = set()
    for scenario in fault_config.scenarios:
        fault_node_ids.update(scenario.node_indices)

    result = {
        "total": len(completed),
        "avg_latency": float(latencies.mean()),
        "p50_latency": p50,
        "p95_latency": float(np.percentile(latencies, 95)),
        "p99_latency": p99,
        "p999_latency": float(np.percentile(latencies, 99.9)),
        "max_latency": float(latencies.max()),
        "tail_ratio": float(p99 / p50) if p50 > 0 else 0.0,
        "throughput": len(completed) / effective_duration,
        "goodput": float((latencies <= config.slo_target).sum() / effective_duration),
        "slo_violation_rate": float((latencies > config.slo_target).mean()),
        "hedge_count": (lit_speculation or speculation).hedge_count if (lit_speculation or speculation) else 0,
        "affected_ratio": float(
            sum(1 for r in completed if r.worker_id in fault_node_ids) / len(completed)
        ) if fault_node_ids else 0.0,
    }

    if verbose:
        print(f"Simulation complete: {config.duration}s ({config.warmup}s warmup)")
        print(f"Total requests: {result['total']}")
        print(f"Avg latency:  {result['avg_latency'] * 1000:.1f}ms")
        print(f"P99 latency:  {result['p99_latency'] * 1000:.1f}ms")
        print(f"Throughput:   {result['throughput']:.0f} req/s")

    return result


def _control_loop(
    env: simpy.Environment,
    config: SimConfig,
    monitor: Monitor,
    detector: Detector,
    selector: StrategySelector,
    aimd: AIMDController,
    balancer: LoadBalancer,
    speculation: SpeculationManager,
    recovery: RecoveryProber,
    collector: MetricsCollector,
) -> simpy.events.Event:
    prev_slo_dist = None
    while True:
        yield env.timeout(config.decision_epoch)
        if monitor.latest is None:
            continue

        metrics = monitor.latest
        severities = detector.compute_severities(metrics, metrics.spare_capacity)
        output = selector.select(severities, metrics.slo_dist, metrics.spare_capacity)

        # AIMD weight updates for SHED nodes only
        aimd_weights = aimd.update(
            output.strategy_map, severities, metrics.slo_dist, prev_slo_dist
        )
        prev_slo_dist = metrics.slo_dist

        # Use min(AIMD, selector) for SHED nodes so both signals are respected
        adjusted_weights: dict[int, float] = {}
        has_adjustments = False
        for wid, strat in output.strategy_map.items():
            if strat == Strategy.SHED:
                aimd_w = aimd_weights.get(wid, 1.0)
                sel_w = output.weight_map.get(wid, 1.0)
                adjusted_weights[wid] = min(aimd_w, sel_w)
                has_adjustments = True
            elif strat == Strategy.ISOLATE:
                adjusted_weights[wid] = 0.0
                has_adjustments = True
            else:
                adjusted_weights[wid] = 1.0

        if has_adjustments:
            balancer.update_weights(adjusted_weights)

        # Handle isolation/recovery with consistent state management
        for wid, strat in output.strategy_map.items():
            if strat == Strategy.ISOLATE:
                balancer.exclude_worker(wid)
                recovery.isolate(wid)
            else:
                # Reintegrate if probes passed, OR if strategy downgraded
                # but node is still excluded (fixes M2: stuck-in-excluded)
                if wid in recovery.reintegration_ready:
                    recovery.reintegrate(wid)
                    balancer.include_worker(wid)
                    # Reset to baseline 1.0, not w_min, to avoid
                    # immediate re-isolation (fixes H1)
                    aimd.reset_weight(wid, 1.0)
                elif wid in recovery.isolated_nodes:
                    # Strategy downgraded from ISOLATE but not yet probed —
                    # keep excluded until probes confirm recovery
                    pass

        # Update speculation manager with per-node hedge decisions
        speculation.strategy_map = output.strategy_map
        speculation.hedge_remaining = metrics.spare_capacity > selector.cfg.spare_min
        speculation.spare_capacity = metrics.spare_capacity
        for wid, nm in metrics.node_metrics.items():
            if nm.p50 > 0:
                speculation.node_p50[wid] = nm.p50

        # Record epoch
        collector.record_epoch(
            time=env.now,
            severities=severities,
            strategies=output.strategy_map,
            weights=adjusted_weights,
            system_p99=metrics.system_p99,
            slo_dist=metrics.slo_dist,
            spare_capacity=metrics.spare_capacity,
        )


def run_danger_zone_validation(output_dir: str = "results") -> None:
    import pandas as pd

    os.makedirs(output_dir, exist_ok=True)

    config = SimConfig(
        n_workers=16,
        load_factor=0.7,
        duration=30.0,
        warmup=5.0,
        seed=42,
    )

    slowdowns = np.arange(1.0, 3.05, 0.1)
    results = []

    print("Danger Zone Validation: sweeping slowdown factor on 1 node")
    print(f"{'s':>5s} | {'P99 (ms)':>10s} | {'Avg (ms)':>10s} | {'Throughput':>10s}")
    print("-" * 45)

    for s in slowdowns:
        fault_cfg = FaultConfig()
        if s > 1.0:
            fault_cfg.scenarios = [FaultScenario(
                node_indices=[0],
                pattern=PermanentFault(slowdown=float(s)),
                onset_time=0.0,
            )]

        result = run_simulation(
            config=config,
            fault_config=fault_cfg,
            enable_mitigation=False,
            verbose=False,
        )
        results.append({
            "slowdown": float(s),
            "p99_ms": result["p99_latency"] * 1000,
            "avg_ms": result["avg_latency"] * 1000,
            "throughput": result["throughput"],
        })
        print(f"{s:5.1f} | {result['p99_latency']*1000:10.1f} | {result['avg_latency']*1000:10.1f} | {result['throughput']:10.0f}")

    df = pd.DataFrame(results)
    csv_path = os.path.join(output_dir, "danger_zone_validation.csv")
    df.to_csv(csv_path, index=False)
    print(f"\nData saved to {csv_path}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 5))
        ax.plot(df["slowdown"], df["p99_ms"], "o-", color="crimson", linewidth=2, markersize=5)
        ax.set_xlabel("Slowdown Factor (s)", fontsize=12)
        ax.set_ylabel("System P99 Latency (ms)", fontsize=12)
        ax.set_title("M/D/1 Danger Zone Validation\n(1 of 16 nodes slowed, 70% load, no mitigation)", fontsize=13)
        ax.axhline(y=config.slo_target * 1000, color="gray", linestyle="--", alpha=0.7, label=f"SLO = {config.slo_target*1000:.0f}ms")
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()

        png_path = os.path.join(output_dir, "danger_zone_validation.png")
        fig.savefig(png_path, dpi=150)
        plt.close(fig)
        print(f"Plot saved to {png_path}")
    except ImportError:
        print("matplotlib not available; skipping plot generation")


def main() -> None:
    parser = argparse.ArgumentParser(description="Slow Fault Simulator")
    parser.add_argument("--validate", action="store_true", help="Run danger zone validation experiment")
    parser.add_argument("--mitigation", action="store_true", help="Enable mitigation strategies")
    args = parser.parse_args()

    if args.validate:
        run_danger_zone_validation()
    else:
        run_simulation(enable_mitigation=args.mitigation)


if __name__ == "__main__":
    main()
