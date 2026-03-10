from __future__ import annotations

import numpy as np

from simulator.control.monitor import SystemMetrics


class Detector:
    # Minimum severity floor: ignore noise below this value.
    MIN_SEVERITY = 0.05

    # V6: Departure-interval service time estimation.
    #
    # In an M/D/1 queue under load, inter-departure times converge to the
    # actual service time d.  By taking a low percentile (P10) of departure
    # intervals, we get a load-invariant estimate of each node's service
    # time.  Severity is then: max(0, 1 - t_base / d_est).
    #
    # This signal is immune to queueing delay — it measures service capacity
    # directly, not end-to-end latency.  Solves the S3/S6 tension because:
    # - S3: healthy nodes at 95% load still depart every ~t_base → severity 0
    # - S6: faulty nodes depart every ~slowdown*t_base → severity > 0
    #
    # CONFIRM_EPOCHS retained to filter transient estimation noise.
    CONFIRM_EPOCHS = 2

    # Minimum number of departure intervals needed for a reliable estimate.
    MIN_INTERVALS = 5

    # Percentile of departure intervals to use as service time estimate.
    # P10 filters out idle gaps (queue-empty periods) while capturing the
    # service-time floor.
    INTERVAL_PERCENTILE = 10

    def __init__(self, t_base: float = 0.01) -> None:
        self.t_base = t_base
        self._consecutive: dict[int, int] = {}

    def compute_severities(self, metrics: SystemMetrics, spare_capacity: float = 1.0) -> dict[int, float]:
        node_metrics = metrics.node_metrics
        if not node_metrics:
            return {}

        severities: dict[int, float] = {}
        for wid, nm in node_metrics.items():
            intervals = nm.departure_intervals

            # Not enough data — cannot estimate service time
            if len(intervals) < self.MIN_INTERVALS:
                severities[wid] = 0.0
                self._consecutive[wid] = 0
                continue

            # Estimate service time from low percentile of departure intervals
            d_est = float(np.percentile(intervals, self.INTERVAL_PERCENTILE))

            # Guard: d_est should be at least t_base; below means estimation noise
            if d_est <= self.t_base:
                severities[wid] = 0.0
                self._consecutive[wid] = 0
                continue

            # Severity: how much slower than expected
            raw_sev = max(0.0, 1.0 - (self.t_base / d_est))
            raw_sev = min(raw_sev, 0.999)
            if raw_sev < self.MIN_SEVERITY:
                raw_sev = 0.0

            # Persistence confirmation
            if raw_sev > 0:
                self._consecutive[wid] = self._consecutive.get(wid, 0) + 1
                if self._consecutive[wid] >= self.CONFIRM_EPOCHS:
                    severities[wid] = raw_sev
                else:
                    severities[wid] = 0.0
            else:
                self._consecutive[wid] = 0
                severities[wid] = 0.0

        return severities
