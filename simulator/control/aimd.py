from __future__ import annotations

from dataclasses import dataclass

from simulator.control import Strategy


@dataclass
class AIMDConfig:
    alpha: float = 0.05
    beta: float = 0.5
    w_min: float = 0.05
    stable_threshold: int = 3


class AIMDController:
    def __init__(self, n_workers: int, config: AIMDConfig | None = None) -> None:
        self.cfg = config or AIMDConfig()
        self._weights: dict[int, float] = {i: 1.0 for i in range(n_workers)}
        self._baselines: dict[int, float] = {i: 1.0 for i in range(n_workers)}
        self._stable_count: dict[int, int] = {i: 0 for i in range(n_workers)}
        self._prev_severity: dict[int, float] = {i: 0.0 for i in range(n_workers)}
        self._isolation_recommendations: set[int] = set()

    @property
    def isolation_recommendations(self) -> set[int]:
        return set(self._isolation_recommendations)

    def get_weight(self, worker_id: int) -> float:
        return self._weights.get(worker_id, 1.0)

    def update(
        self,
        strategy_map: dict[int, Strategy],
        severities: dict[int, float],
        slo_dist: float,
        prev_slo_dist: float | None = None,
    ) -> dict[int, float]:
        self._isolation_recommendations.clear()

        for wid, strat in strategy_map.items():
            if strat != Strategy.SHED:
                if strat == Strategy.NORMAL or strat == Strategy.SPECULATE:
                    self._weights[wid] = self._baselines.get(wid, 1.0)
                    self._stable_count[wid] = 0
                continue

            sev = severities.get(wid, 0.0)
            prev_sev = self._prev_severity.get(wid, 0.0)
            slo_decreasing = prev_slo_dist is not None and slo_dist < prev_slo_dist

            if sev > prev_sev or slo_decreasing:
                self._weights[wid] = max(
                    self._weights.get(wid, 1.0) * self.cfg.beta,
                    self.cfg.w_min,
                )
                self._stable_count[wid] = 0
                if self._weights[wid] <= self.cfg.w_min:
                    self._isolation_recommendations.add(wid)
            else:
                self._stable_count[wid] = self._stable_count.get(wid, 0) + 1
                if self._stable_count[wid] >= self.cfg.stable_threshold:
                    baseline = self._baselines.get(wid, 1.0)
                    self._weights[wid] = min(
                        self._weights.get(wid, 1.0) + self.cfg.alpha,
                        baseline,
                    )

        self._prev_severity = dict(severities)

        # Return raw weights — do NOT normalize here.
        # The control loop is responsible for applying weights only to
        # SHED/ISOLATE nodes. Normalizing all weights (including NORMAL
        # nodes) causes cascading weight redistribution that destabilizes
        # the system even without faults.
        return dict(self._weights)

    def set_baseline(self, worker_id: int, baseline: float) -> None:
        self._baselines[worker_id] = baseline

    def reset_weight(self, worker_id: int, weight: float | None = None) -> None:
        if weight is None:
            weight = self._baselines.get(worker_id, 1.0)
        self._weights[worker_id] = weight
        self._stable_count[worker_id] = 0
