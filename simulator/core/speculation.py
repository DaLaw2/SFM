from __future__ import annotations

import simpy

from simulator.config import SimConfig
from simulator.control import Strategy
from simulator.core.balancer import LoadBalancer
from simulator.core.request import Request
from simulator.core.worker import WorkerNode


class SpeculationManager:
    def __init__(
        self,
        env: simpy.Environment,
        config: SimConfig,
        balancer: LoadBalancer,
        workers: list[WorkerNode],
        unconditional: bool = False,
        hedge_delay_override: float | None = None,
    ) -> None:
        self.env = env
        self.config = config
        self.balancer = balancer
        self.workers = {w.worker_id: w for w in workers}
        self.strategy_map: dict[int, Strategy] = {}
        self.hedge_remaining: bool = True
        self.node_p50: dict[int, float] = {}
        self.hedge_count: int = 0
        self.cancel_count: int = 0
        self._next_hedge_id: int = 0
        # M3: Hedge rate budget — limit hedges per decision epoch to a
        # fraction of spare capacity (in req/epoch units).
        self.hedge_budget_fraction: float = 0.5
        self.spare_capacity: float = 0.0  # updated by control loop
        self._hedge_epoch_count: int = 0
        self._last_epoch_time: float = 0.0
        # Literature baseline modes
        self.unconditional: bool = unconditional
        self.hedge_delay_override: float | None = hedge_delay_override

    def should_hedge(self, worker_id: int) -> bool:
        if self.unconditional:
            # Budget: limit hedge overhead to ~10% of total capacity
            epoch = self.config.decision_epoch
            if self.env.now - self._last_epoch_time >= epoch:
                self._hedge_epoch_count = 0
                self._last_epoch_time += epoch
            max_hedges = int(0.10 * self.config.total_capacity * epoch)
            if self._hedge_epoch_count >= max_hedges:
                return False
            self._hedge_epoch_count += 1
            return True
        strat = self.strategy_map.get(worker_id, Strategy.NORMAL)
        if strat not in (Strategy.SPECULATE, Strategy.SHED):
            return False
        if strat == Strategy.SHED and not self.hedge_remaining:
            return False
        # M3: Check hedge rate budget
        epoch = self.config.decision_epoch
        if self.env.now - self._last_epoch_time >= epoch:
            self._hedge_epoch_count = 0
            self._last_epoch_time += epoch
        # Use healthy worker count for budget (consistent with M1 spare_capacity denominator)
        n_healthy = sum(1 for w in self.workers.values() if w.slowdown_factor <= 1.0)
        healthy_cap = self.config.capacity_per_worker * n_healthy
        raw_budget = int(self.spare_capacity * healthy_cap * epoch * self.hedge_budget_fraction)
        # No floor of 1: when spare_capacity is 0, block all hedges
        budget = max(0, raw_budget)
        if self._hedge_epoch_count >= budget:
            return False
        # Reserve the slot immediately to prevent budget overshoot under bursts
        self._hedge_epoch_count += 1
        return True

    def submit_with_hedge(
        self,
        request: Request,
        slow_worker_id: int,
        hedge_delay: float | None = None,
    ) -> simpy.events.Event:
        """Submit request to slow worker AND a hedge copy to a healthy worker.

        Returns a SimPy event that triggers when the first response arrives.
        The other is cancelled.
        """
        slow_worker = self.workers[slow_worker_id]
        if hedge_delay is None:
            hedge_delay = self.node_p50.get(slow_worker_id, self.config.t_base)
        return self.env.process(self._hedge_process(request, slow_worker, hedge_delay))

    def dispatch_hedged(
        self, request: Request, primary_worker: WorkerNode
    ) -> simpy.events.Event:
        if self.hedge_delay_override is not None:
            hedge_delay = self.hedge_delay_override
        else:
            hedge_delay = self.node_p50.get(primary_worker.worker_id, self.config.t_base)
        return self.env.process(self._hedge_process(request, primary_worker, hedge_delay))

    def _hedge_process(
        self, request: Request, primary_worker: WorkerNode, hedge_delay: float
    ) -> simpy.events.Event:
        self._next_hedge_id += 1
        hedge_request = Request(
            id=request.id,
            arrival_time=request.arrival_time,
            is_hedge=True,
        )

        # Start primary immediately
        primary_event = primary_worker.process(request)

        # Wait hedge_delay then dispatch hedge copy to a healthy worker
        if hedge_delay > 0:
            yield self.env.timeout(hedge_delay)

        if request.end_time > 0:
            # Primary already completed during delay
            return

        healthy_worker = self._pick_healthy_worker(primary_worker.worker_id)
        if healthy_worker is None:
            return

        self.hedge_count += 1
        hedge_event = healthy_worker.process(hedge_request)

        # Wait for either to complete
        result = yield primary_event | hedge_event

        # Cancel the slower one
        if request.end_time > 0 and hedge_request.end_time <= 0:
            hedge_request.cancelled = True
            self.cancel_count += 1
        elif hedge_request.end_time > 0 and request.end_time <= 0:
            request.cancelled = True
            self.cancel_count += 1
            # Copy timing from hedge to primary for metric purposes
            request.start_time = hedge_request.start_time
            request.end_time = hedge_request.end_time
            request.worker_id = hedge_request.worker_id

    def _pick_healthy_worker(self, exclude_id: int) -> WorkerNode | None:
        if self.unconditional:
            # Literature baseline: pick any other worker by shortest queue
            candidates = [
                w for wid, w in self.workers.items() if wid != exclude_id
            ]
        else:
            candidates = [
                w for wid, w in self.workers.items()
                if wid != exclude_id
                and self.strategy_map.get(wid, Strategy.NORMAL) == Strategy.NORMAL
            ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda w: len(w.resource.queue) + len(w.resource.users),
        )
