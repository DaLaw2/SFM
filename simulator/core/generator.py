from __future__ import annotations

from typing import TYPE_CHECKING

import simpy
import numpy as np

from simulator.config import SimConfig
from simulator.core.request import Request
from simulator.core.balancer import LoadBalancer

if TYPE_CHECKING:
    from simulator.core.speculation import SpeculationManager


class RequestGenerator:
    def __init__(
        self,
        env: simpy.Environment,
        config: SimConfig,
        balancer: LoadBalancer,
        rng: np.random.Generator,
        load_schedule: list[tuple[float, float]] | None = None,
        speculation: SpeculationManager | None = None,
    ) -> None:
        self.env = env
        self.config = config
        self.balancer = balancer
        self.rng = rng
        self.speculation = speculation
        self._next_id = 0
        self.all_requests: list[Request] = []
        # load_schedule: list of (time, load_factor) pairs, sorted by time.
        # The generator adjusts its arrival rate when sim time crosses each threshold.
        self._load_schedule = sorted(load_schedule, key=lambda x: x[0]) if load_schedule else None

    def run(self) -> simpy.events.Event:
        return self.env.process(self._generate())

    def _current_rate(self) -> float:
        """Return the arrival rate for the current simulation time."""
        if not self._load_schedule:
            return self.config.arrival_rate
        # Find the latest schedule entry at or before current time
        load_factor = self.config.load_factor
        for t_threshold, lf in self._load_schedule:
            if self.env.now >= t_threshold:
                load_factor = lf
            else:
                break
        return load_factor * self.config.total_capacity

    def _generate(self) -> simpy.events.Event:
        while True:
            rate = self._current_rate()
            inter_arrival = self.rng.exponential(1.0 / rate)
            yield self.env.timeout(inter_arrival)

            request = Request(id=self._next_id, arrival_time=self.env.now)
            self._next_id += 1
            self.all_requests.append(request)

            worker = self.balancer.select_worker()
            if (
                self.speculation is not None
                and self.speculation.should_hedge(worker.worker_id)
            ):
                self.speculation.dispatch_hedged(request, worker)
            else:
                worker.process(request)
