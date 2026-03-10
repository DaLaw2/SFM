from __future__ import annotations

import numpy as np

from simulator.core.worker import WorkerNode


class LoadBalancer:
    def __init__(self, workers: list[WorkerNode], rng: np.random.Generator,
                 strategy: str = "p2c") -> None:
        self.workers = workers
        self.rng = rng
        self.strategy = strategy
        self._weights: dict[int, float] = {w.worker_id: 1.0 for w in workers}
        self._excluded: set[int] = set()

    def _get_available(self) -> list[WorkerNode]:
        available = [w for w in self.workers if w.worker_id not in self._excluded]
        if not available:
            available = [w for w in self.workers if self._weights.get(w.worker_id, 1.0) > 0]
            if not available:
                available = self.workers
        return available

    @staticmethod
    def _queue_depth(w: WorkerNode) -> int:
        return len(w.resource.queue) + len(w.resource.users)

    def select_worker(self) -> WorkerNode:
        available = self._get_available()
        if len(available) == 1:
            return available[0]

        if self.strategy == "lor":
            return self._select_lor(available)
        if self.strategy == "weighted_random":
            return self._select_weighted_random(available)
        return self._select_p2c(available)

    def _select_p2c(self, available: list[WorkerNode]) -> WorkerNode:
        weights = np.array([self._weights.get(w.worker_id, 1.0) for w in available])
        total = weights.sum()
        if total <= 0:
            probs = np.ones(len(available)) / len(available)
        else:
            probs = weights / total

        k = min(2, len(available))
        idxs = self.rng.choice(len(available), size=k, replace=False, p=probs)
        candidates = [available[i] for i in idxs]
        return min(candidates, key=self._queue_depth)

    def _select_weighted_random(self, available: list[WorkerNode]) -> WorkerNode:
        """Weighted random: select by weight only, no queue-depth comparison."""
        weights = np.array([self._weights.get(w.worker_id, 1.0) for w in available])
        total = weights.sum()
        if total <= 0:
            probs = np.ones(len(available)) / len(available)
        else:
            probs = weights / total
        idx = self.rng.choice(len(available), p=probs)
        return available[idx]

    def _select_lor(self, available: list[WorkerNode]) -> WorkerNode:
        """Least-Outstanding-Requests: pick the worker with the shortest queue."""
        return min(available, key=self._queue_depth)

    def update_weights(self, weights: dict[int, float]) -> None:
        self._weights.update(weights)

    def exclude_worker(self, worker_id: int) -> None:
        self._excluded.add(worker_id)

    def include_worker(self, worker_id: int) -> None:
        self._excluded.discard(worker_id)
