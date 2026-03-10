from __future__ import annotations

import numpy as np
import simpy

from simulator.config import SimConfig
from simulator.core.request import Request


class WorkerNode:
    def __init__(self, env: simpy.Environment, worker_id: int, config: SimConfig,
                 rng: np.random.Generator | None = None) -> None:
        self.env = env
        self.worker_id = worker_id
        self.config = config
        self.resource = simpy.Resource(env, capacity=1)
        self.slowdown_factor: float = 1.0
        self.completed: list[Request] = []
        self._rng = rng

    @property
    def service_time(self) -> float:
        """Mean service time (used by external code for estimation)."""
        return self.config.t_base * self.slowdown_factor

    def _sample_service_time(self) -> float:
        """Sample a service time: deterministic (M/D/1) or variable (M/G/1)."""
        mean = self.service_time
        cv = self.config.service_cv
        if cv <= 0.0 or self._rng is None:
            return mean
        # Gamma distribution with given mean and CV
        # shape = 1/CV^2, scale = mean * CV^2
        shape = 1.0 / (cv * cv)
        scale = mean * cv * cv
        return float(self._rng.gamma(shape, scale))

    def process(self, request: Request) -> simpy.events.Event:
        return self.env.process(self._handle(request))

    def _handle(self, request: Request) -> simpy.events.Event:
        with self.resource.request() as req:
            yield req
            if request.cancelled:
                return
            request.start_time = self.env.now
            request.worker_id = self.worker_id
            yield self.env.timeout(self._sample_service_time())
            request.end_time = self.env.now
            if not request.is_probe:
                self.completed.append(request)
