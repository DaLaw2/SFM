from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FaultConfig:
    """Configuration for fault injection.

    Attributes:
        scenarios: List of FaultScenario objects to inject.
        update_interval: How often (sim-time seconds) the injector refreshes
            slowdown values on workers.  Default 0.01 (10 ms).
    """
    scenarios: list = field(default_factory=list)
    update_interval: float = 0.01


@dataclass
class StrategyConfig:
    theta_spec: float = 0.1
    theta_shed: float = 0.3
    theta_iso: float = 0.5
    spare_min: float = 0.15
    hysteresis: float = 0.05
    debounce: int = 2
    aimd_alpha: float = 0.05
    aimd_beta: float = 0.5
    w_min: float = 0.05
    hedge_delay_factor: float = 1.0
    max_isolation_fraction: float = 0.25  # G2: isolate at most N/4 nodes


@dataclass
class SimConfig:
    n_workers: int = 16
    capacity_per_worker: float = 100.0  # req/s
    t_base: float = 0.01  # 10ms base service time (1/capacity_per_worker)
    slo_target: float = 0.05  # 50ms P99 target
    slo_percentile: float = 0.99
    duration: float = 60.0  # simulation duration in seconds
    warmup: float = 10.0  # warmup period
    load_factor: float = 0.7  # fraction of total capacity
    decision_epoch: float = 0.5  # 500ms
    seed: int = 42
    service_cv: float = 0.0  # Coefficient of variation: 0=M/D/1, >0=M/G/1
    balancer_strategy: str = "p2c"  # "p2c" or "lor"

    @property
    def total_capacity(self) -> float:
        return self.n_workers * self.capacity_per_worker

    @property
    def arrival_rate(self) -> float:
        return self.load_factor * self.total_capacity
