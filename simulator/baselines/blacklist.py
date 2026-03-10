"""Outlier blacklisting baseline (Cassandra dynamic snitch style).

Periodically checks per-node latency. If a node's median latency exceeds
k * cluster_median, blacklist it (exclude from routing). Unblacklist after
cooldown_epochs of normal latency.

No severity estimation, no escalation, no weight adjustment — just binary
blacklist/unblacklist decisions.
"""
from __future__ import annotations

import numpy as np
import simpy

from simulator.core.balancer import LoadBalancer
from simulator.control.monitor import Monitor


class OutlierBlacklist:
    def __init__(
        self,
        env: simpy.Environment,
        monitor: Monitor,
        balancer: LoadBalancer,
        epoch: float = 0.5,
        k_threshold: float = 2.0,
        cooldown_epochs: int = 3,
    ) -> None:
        self.env = env
        self.monitor = monitor
        self.balancer = balancer
        self.epoch = epoch
        self.k_threshold = k_threshold
        self.cooldown_epochs = cooldown_epochs
        self._blacklisted: set[int] = set()
        self._normal_count: dict[int, int] = {}  # epochs below threshold

    def run(self) -> simpy.events.Event:
        return self.env.process(self._loop())

    def _loop(self) -> simpy.events.Event:
        while True:
            yield self.env.timeout(self.epoch)
            if self.monitor.latest is None:
                continue

            node_medians: dict[int, float] = {}
            for wid, nm in self.monitor.latest.node_metrics.items():
                if nm.latencies:
                    node_medians[wid] = float(np.median(nm.latencies))

            if not node_medians:
                continue

            all_medians = list(node_medians.values())
            cluster_median = float(np.median(all_medians))
            threshold = cluster_median * self.k_threshold

            for wid, med in node_medians.items():
                if med > threshold:
                    if wid not in self._blacklisted:
                        self.balancer.exclude_worker(wid)
                        self._blacklisted.add(wid)
                    self._normal_count[wid] = 0
                else:
                    if wid in self._blacklisted:
                        self._normal_count[wid] = self._normal_count.get(wid, 0) + 1
                        if self._normal_count[wid] >= self.cooldown_epochs:
                            self.balancer.include_worker(wid)
                            self._blacklisted.discard(wid)
                            self._normal_count[wid] = 0
