"""FaultInjector -- SimPy process that applies slowdown factors to workers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import simpy

if TYPE_CHECKING:
    from simulator.fault import FaultScenario


class FaultInjector:
    """Periodically updates ``slowdown_factor`` on target worker nodes.

    This is a SimPy process.  Start it with::

        env.process(injector.run())

    Parameters
    ----------
    env : simpy.Environment
        The SimPy simulation environment.
    workers : list
        Worker objects that expose a ``slowdown_factor`` attribute.
    scenarios : list[FaultScenario]
        Fault scenarios to inject.
    update_interval : float
        How often (in simulation time) to refresh slowdown values.
    """

    def __init__(
        self,
        env: simpy.Environment,
        workers: list,
        scenarios: list[FaultScenario],
        update_interval: float = 0.01,
    ) -> None:
        self.env = env
        self.workers = workers
        self.scenarios = scenarios
        self.update_interval = update_interval

    def _is_active(self, scenario: FaultScenario) -> bool:
        """Return True if the scenario is currently active."""
        now = self.env.now
        if now < scenario.onset_time:
            return False
        if scenario.duration is not None:
            if now > scenario.onset_time + scenario.duration:
                return False
        return True

    def run(self):
        """SimPy generator process: update slowdown_factor on target workers."""
        while True:
            # Collect max slowdown per node across all active scenarios
            node_slowdowns: dict[int, float] = {}

            for scenario in self.scenarios:
                active = self._is_active(scenario)
                for node_idx in scenario.node_indices:
                    if not active:
                        continue
                    slowdown = scenario.pattern.get_slowdown(
                        self.env.now, scenario.onset_time
                    )
                    slowdown = max(1.0, slowdown)
                    node_slowdowns[node_idx] = max(
                        node_slowdowns.get(node_idx, 1.0), slowdown
                    )

            # Apply: nodes with active faults get max slowdown, others reset
            affected = set(node_slowdowns.keys())
            for scenario in self.scenarios:
                for node_idx in scenario.node_indices:
                    if node_idx in affected:
                        self.workers[node_idx].slowdown_factor = node_slowdowns[node_idx]
                    else:
                        self.workers[node_idx].slowdown_factor = 1.0

            yield self.env.timeout(self.update_interval)
