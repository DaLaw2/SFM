from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import simpy

from simulator.config import SimConfig
from simulator.core.worker import WorkerNode


@dataclass
class NodeMetrics:
    worker_id: int
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    throughput: float = 0.0
    queue_depth: int = 0
    latencies: list[float] = field(default_factory=list)
    departure_intervals: list[float] = field(default_factory=list)


@dataclass
class SystemMetrics:
    time: float
    node_metrics: dict[int, NodeMetrics] = field(default_factory=dict)
    system_p99: float = 0.0
    total_throughput: float = 0.0
    spare_capacity: float = 0.0
    slo_dist: float = 1.0


class Monitor:
    def __init__(
        self,
        env: simpy.Environment,
        config: SimConfig,
        workers: list[WorkerNode],
    ) -> None:
        self.env = env
        self.config = config
        self.workers = workers
        self._prev_completed: dict[int, int] = {w.worker_id: 0 for w in workers}
        self.latest: SystemMetrics | None = None
        self.history: list[SystemMetrics] = []
        # EMA smoothing factor for spare_capacity to dampen M1/M3 feedback oscillation
        self._ema_alpha: float = 0.3
        self._ema_spare: float | None = None

    def run(self) -> simpy.events.Event:
        return self.env.process(self._monitor_loop())

    def _monitor_loop(self) -> simpy.events.Event:
        while True:
            yield self.env.timeout(self.config.decision_epoch)
            self.latest = self._collect()
            self.history.append(self.latest)

    def _collect(self) -> SystemMetrics:
        tau = self.config.decision_epoch
        all_latencies: list[float] = []
        node_metrics: dict[int, NodeMetrics] = {}
        total_throughput = 0.0

        for w in self.workers:
            prev = self._prev_completed[w.worker_id]
            recent = w.completed[prev:]
            self._prev_completed[w.worker_id] = len(w.completed)

            completed_recent = [r for r in recent if r.end_time > 0]
            lats = [r.latency for r in completed_recent]
            nm = NodeMetrics(worker_id=w.worker_id)
            nm.queue_depth = len(w.resource.queue) + len(w.resource.users)
            nm.latencies = lats

            # Compute inter-departure intervals for service time estimation.
            # Sort by end_time to get departure order, then diff.
            if len(completed_recent) >= 2:
                end_times = sorted(r.end_time for r in completed_recent)
                nm.departure_intervals = [
                    end_times[i + 1] - end_times[i]
                    for i in range(len(end_times) - 1)
                ]

            if lats:
                arr = np.array(lats)
                nm.p50 = float(np.percentile(arr, 50))
                nm.p95 = float(np.percentile(arr, 95))
                nm.p99 = float(np.percentile(arr, 99))
                nm.throughput = len(lats) / tau
                all_latencies.extend(lats)

            total_throughput += nm.throughput
            node_metrics[w.worker_id] = nm

        sm = SystemMetrics(time=self.env.now, node_metrics=node_metrics)
        sm.total_throughput = total_throughput

        if all_latencies:
            sm.system_p99 = float(np.percentile(all_latencies, 99))

        healthy_capacity = sum(
            self.config.capacity_per_worker
            for w in self.workers
            if w.slowdown_factor <= 1.0
        )
        if healthy_capacity > 0:
            # M1: Use observed throughput (includes hedge traffic) instead of
            # static arrival_rate, so spare_capacity reflects actual load.
            observed_load = total_throughput
            raw_spare = max(0.0, 1.0 - (observed_load / healthy_capacity))
        else:
            raw_spare = 0.0

        # EMA smoothing to dampen M1/M3 feedback oscillation
        if self._ema_spare is None:
            self._ema_spare = raw_spare
        else:
            self._ema_spare = self._ema_alpha * raw_spare + (1.0 - self._ema_alpha) * self._ema_spare
        sm.spare_capacity = self._ema_spare

        if self.config.slo_target > 0:
            sm.slo_dist = (self.config.slo_target - sm.system_p99) / self.config.slo_target

        return sm
