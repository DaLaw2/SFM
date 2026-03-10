from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import simpy

from simulator.config import SimConfig
from simulator.core.request import Request
from simulator.core.worker import WorkerNode


@dataclass
class RecoveryConfig:
    tau_probe: float = 30.0
    n_probe: int = 5
    theta_recovery: float = 0.15


@dataclass
class ProbeResult:
    worker_id: int
    time: float
    severity: float
    avg_latency: float


class RecoveryProber:
    def __init__(
        self,
        env: simpy.Environment,
        config: SimConfig,
        workers: list[WorkerNode],
        recovery_config: RecoveryConfig | None = None,
    ) -> None:
        self.env = env
        self.config = config
        self.workers = {w.worker_id: w for w in workers}
        self.rcfg = recovery_config or RecoveryConfig()
        self.isolated_nodes: set[int] = set()
        self.reintegration_ready: set[int] = set()
        self.probe_history: list[ProbeResult] = []
        self._next_probe_id: int = 1_000_000

    def run(self) -> simpy.events.Event:
        return self.env.process(self._probe_loop())

    def isolate(self, worker_id: int) -> None:
        self.isolated_nodes.add(worker_id)
        self.reintegration_ready.discard(worker_id)

    def reintegrate(self, worker_id: int) -> None:
        self.isolated_nodes.discard(worker_id)
        self.reintegration_ready.discard(worker_id)

    def _probe_loop(self) -> simpy.events.Event:
        while True:
            yield self.env.timeout(self.rcfg.tau_probe)
            # Probe all isolated nodes in parallel instead of sequentially
            probes = [
                self.env.process(self._probe_node(wid))
                for wid in list(self.isolated_nodes)
            ]
            if probes:
                yield self.env.all_of(probes)

    def _probe_node(self, worker_id: int) -> simpy.events.Event:
        worker = self.workers.get(worker_id)
        if worker is None:
            return

        latencies: list[float] = []
        for i in range(self.rcfg.n_probe):
            self._next_probe_id += 1
            probe_req = Request(
                id=self._next_probe_id,
                arrival_time=self.env.now,
                is_probe=True,
            )
            yield worker.process(probe_req)
            if probe_req.end_time > 0:
                latencies.append(probe_req.latency)

        if not latencies:
            return

        avg_lat = np.mean(latencies)
        # severity from latency vs expected base
        if avg_lat > self.config.t_base:
            severity = 1.0 - (self.config.t_base / avg_lat)
        else:
            severity = 0.0

        result = ProbeResult(
            worker_id=worker_id,
            time=self.env.now,
            severity=severity,
            avg_latency=float(avg_lat),
        )
        self.probe_history.append(result)

        if severity < self.rcfg.theta_recovery:
            self.reintegration_ready.add(worker_id)
