"""Bridge between GPU simulation state and CPU control plane.

Extracts per-epoch metrics from JAX arrays and formats them for the
existing Detector/Selector/AIMD components (which operate on numpy/Python).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import jax
import jax.numpy as jnp
import numpy as np

from simulator.config import SimConfig, StrategyConfig
from simulator.control import Strategy
from simulator.control.detector import Detector
from simulator.control.selector import StrategySelector
from simulator.control.aimd import AIMDController, AIMDConfig
from simulator.control.monitor import NodeMetrics, SystemMetrics
from simulator_gpu.config import GPUConfig
from simulator_gpu.state import SimState


@dataclass
class EpochMetrics:
    """Metrics extracted from GPU state at the end of an epoch."""
    node_metrics: dict[int, NodeMetrics]
    system_p99: float
    total_throughput: float
    spare_capacity: float
    slo_dist: float


class ControlBridge:
    """Runs the CPU-side control plane for the GPU simulator.

    Each epoch:
    1. Extract metrics from GPU state (departure intervals, queue depths)
    2. Compute severities via Detector
    3. Select strategies via Selector
    4. Update AIMD weights
    5. Return new weights and exclusion masks for GPU state
    """

    def __init__(
        self,
        sim_config: SimConfig,
        gpu_config: GPUConfig,
        strategy_config: StrategyConfig | None = None,
    ) -> None:
        self.sim_config = sim_config
        self.gpu_config = gpu_config
        self.scfg = strategy_config or StrategyConfig()

        N = sim_config.n_workers
        node_ids = list(range(N))

        self.detector = Detector(t_base=sim_config.t_base)
        self.selector = StrategySelector(node_ids, self.scfg)
        self.aimd = AIMDController(N, AIMDConfig(
            alpha=self.scfg.aimd_alpha,
            beta=self.scfg.aimd_beta,
            w_min=self.scfg.w_min,
        ))

        self._prev_histogram: np.ndarray | None = None
        self._prev_completed: int = 0
        self._prev_slo_dist: float | None = None
        self._ema_spare: float | None = None
        self._ema_alpha: float = 0.3

        # Track departure_tail per epoch to extract only current-epoch intervals
        self._prev_dep_tail: np.ndarray = np.zeros(N, dtype=np.int32)

        # Probe-based recovery (DR-009): isolated nodes get periodic probe
        # epochs with low weight, providing an observation channel.
        self._isolated_nodes: set[int] = set()
        self._isolation_epoch: dict[int, int] = {}  # wid -> epoch when isolated
        self._recovery_count: dict[int, int] = {}   # consecutive healthy readings
        self._current_epoch: int = 0

        # Probe parameters (see DR-009 for derivation)
        self.PROBE_WEIGHT = 0.14   # yields ~5 arrivals during probe epoch
        self.MIN_HOLD_EPOCHS = 4   # 2s minimum before first probe
        self.PROBE_INTERVAL = 8    # 4s between probes per node
        self.RECOVERY_CONFIRM = 2  # consecutive healthy probes to un-isolate
        self.PROBATION_WEIGHT = 0.5  # reduced weight during post-recovery probation
        self.PROBATION_EPOCHS = 4    # epochs at reduced weight after recovery
        # Align with SimPy's theta_recovery=0.15 for probe severity threshold
        self.PROBE_THETA = 0.15

        self._probe_epoch: dict[int, int] = {}  # wid -> next epoch to probe
        self._probing_now: set[int] = set()      # nodes being probed THIS epoch
        # Post-recovery probation: gradual reintegration (fix #8)
        self._probation_nodes: dict[int, int] = {}  # wid -> epoch probation ends

        # Max simultaneous isolations: respect capacity budget (fix #1)
        self._max_isolated = max(1, N // 4)

    def extract_metrics(self, state: SimState) -> EpochMetrics:
        """Extract per-epoch metrics from GPU state.

        Pulls JAX arrays to CPU (numpy) and computes node-level and
        system-level metrics for the control plane.
        """
        N = self.sim_config.n_workers
        dt = self.gpu_config.dt
        tau = self.sim_config.decision_epoch  # epoch duration in seconds
        D = self.gpu_config.departure_buf_size

        # Pull arrays to numpy
        dep_intervals = np.array(state.departure_intervals)  # [N, D]
        dep_tail = np.array(state.departure_tail)  # [N]
        queue_lengths = np.array(state.queue_lengths)  # [N]
        histogram = np.array(state.histogram)  # [B]
        total_completed = int(state.total_completed)
        slowdown_factors = np.array(state.slowdown_factors)  # [N]

        # Compute per-epoch histogram delta
        if self._prev_histogram is None:
            epoch_hist = histogram.copy()
        else:
            epoch_hist = histogram - self._prev_histogram
        self._prev_histogram = histogram.copy()

        # Epoch completions
        epoch_completed = total_completed - self._prev_completed
        self._prev_completed = total_completed

        # System P99 from epoch histogram
        epoch_total = epoch_hist.sum()
        system_p99 = 0.0
        if epoch_total > 0:
            cumsum = np.cumsum(epoch_hist)
            p99_bin = np.searchsorted(cumsum, epoch_total * 0.99, side="left")
            system_p99 = p99_bin * dt

        # Per-node metrics from departure intervals
        node_metrics: dict[int, NodeMetrics] = {}
        total_throughput = 0.0

        for wid in range(N):
            nm = NodeMetrics(worker_id=wid)
            nm.queue_depth = int(queue_lengths[wid])

            # Extract only current-epoch departure intervals from circular buffer
            prev_tail = int(self._prev_dep_tail[wid])
            tail = int(dep_tail[wid])
            n_epoch = tail - prev_tail  # new departures this epoch
            n_epoch = max(0, min(n_epoch, D))  # clamp to [0, D]

            if n_epoch > 0:
                indices = [(prev_tail + j) % D for j in range(n_epoch)]
                intervals_steps = dep_intervals[wid, indices]

                # Convert steps to seconds
                nm.departure_intervals = (intervals_steps * dt).tolist()

            # Estimate throughput from epoch departures
            if n_epoch > 0:
                nm.throughput = n_epoch / tau
            total_throughput += nm.throughput

            node_metrics[wid] = nm

        # Update prev_dep_tail for next epoch
        self._prev_dep_tail = dep_tail.copy()

        # Spare capacity (EMA smoothed)
        healthy_capacity = sum(
            self.sim_config.capacity_per_worker
            for wid in range(N)
            if slowdown_factors[wid] <= 1.0
        )
        if healthy_capacity > 0:
            raw_spare = max(0.0, 1.0 - total_throughput / healthy_capacity)
        else:
            raw_spare = 0.0

        if self._ema_spare is None:
            self._ema_spare = raw_spare
        else:
            self._ema_spare = self._ema_alpha * raw_spare + (1 - self._ema_alpha) * self._ema_spare

        # SLO distance
        slo_dist = 1.0
        if self.sim_config.slo_target > 0:
            slo_dist = (self.sim_config.slo_target - system_p99) / self.sim_config.slo_target

        return EpochMetrics(
            node_metrics=node_metrics,
            system_p99=system_p99,
            total_throughput=total_throughput,
            spare_capacity=self._ema_spare,
            slo_dist=slo_dist,
        )

    def _compute_probe_severity(self, intervals: list[float]) -> float:
        """Compute severity from probe departure intervals.

        Uses median instead of P10 for robustness with small sample sizes
        (~5 intervals). Aligns with SimPy's mean(latency) approach — for
        isolated nodes with no queueing, median ≈ mean of service times.
        """
        if not intervals:
            return 0.0
        d_est = float(np.median(intervals))
        if d_est > self.sim_config.t_base:
            return min(0.999, 1.0 - (self.sim_config.t_base / d_est))
        return 0.0

    def step(self, state: SimState) -> tuple[jax.Array, jax.Array]:
        """Run one control plane step. Returns (new_weights, new_excluded).

        This is called once per epoch from the simulation loop.
        """
        self._current_epoch += 1
        N = self.sim_config.n_workers

        metrics = self.extract_metrics(state)

        # Build SystemMetrics for the detector
        sys_metrics = SystemMetrics(
            time=float(state.step) * self.gpu_config.dt,
            node_metrics=metrics.node_metrics,
            system_p99=metrics.system_p99,
            total_throughput=metrics.total_throughput,
            spare_capacity=metrics.spare_capacity,
            slo_dist=metrics.slo_dist,
        )

        # Detect severities
        severities = self.detector.compute_severities(sys_metrics, metrics.spare_capacity)

        # Select strategies
        output = self.selector.select(severities, metrics.slo_dist, metrics.spare_capacity)

        # AIMD weight updates for SHED nodes
        aimd_weights = self.aimd.update(
            output.strategy_map, severities, metrics.slo_dist, self._prev_slo_dist,
        )
        self._prev_slo_dist = metrics.slo_dist

        # Compute final weights (min of AIMD and selector for SHED)
        weights = np.ones(N, dtype=np.float32)
        excluded = np.zeros(N, dtype=np.bool_)

        for wid, strat in output.strategy_map.items():
            if strat == Strategy.SHED:
                aimd_w = aimd_weights.get(wid, 1.0)
                sel_w = output.weight_map.get(wid, 1.0)
                weights[wid] = min(aimd_w, sel_w)
            elif strat == Strategy.ISOLATE:
                if wid not in self._isolated_nodes:
                    # Check capacity budget before isolating (fix #1)
                    if len(self._isolated_nodes) < self._max_isolated:
                        self._isolated_nodes.add(wid)
                        self._isolation_epoch[wid] = self._current_epoch
                        self._recovery_count[wid] = 0
                        self._probe_epoch[wid] = self._current_epoch + self.MIN_HOLD_EPOCHS
                    else:
                        # Budget exceeded — fall back to SHED weight
                        sel_w = output.weight_map.get(wid, 0.5)
                        weights[wid] = max(self.scfg.w_min, sel_w)
                        continue
                weights[wid] = 0.0
                excluded[wid] = True
            else:
                weights[wid] = 1.0

        # Post-recovery probation: reduced weight, but respect escalation.
        # Runs BEFORE isolation override so re-isolation takes priority.
        for wid in list(self._probation_nodes):
            end_epoch = self._probation_nodes[wid]
            if self._current_epoch >= end_epoch:
                self._probation_nodes.pop(wid)
            else:
                # Probation weight is a ceiling — SHED can reduce further
                strat = output.strategy_map.get(wid, Strategy.NORMAL)
                if strat == Strategy.SHED:
                    weights[wid] = min(self.PROBATION_WEIGHT, weights[wid])
                elif strat == Strategy.ISOLATE:
                    # Re-faulted during probation — exit probation, re-isolate
                    self._probation_nodes.pop(wid)
                else:
                    weights[wid] = self.PROBATION_WEIGHT

        # Override: nodes in _isolated_nodes stay isolated regardless of
        # what the Selector says this epoch (Selector may rotate strategies
        # due to capacity budget, assigning SHED instead of ISOLATE).
        # Runs AFTER probation so isolation always wins.
        for wid in self._isolated_nodes:
            weights[wid] = 0.0
            excluded[wid] = True
            self._probation_nodes.pop(wid, None)  # clean up if re-isolated

        # Periodic probe-based recovery (DR-009):
        # - Evaluate nodes that were probed in the epoch that just ran
        # - Schedule probe weight for at most one node due next epoch
        min_intervals = self.detector.MIN_INTERVALS

        # Step 1: Evaluate probe results from nodes probed last epoch.
        # Compute severity directly from probe intervals using median (fix #3),
        # bypassing the detector's CONFIRM_EPOCHS (already confirmed before
        # isolation). Use PROBE_THETA aligned with SimPy's theta_recovery (fix #5).
        for wid in list(self._probing_now):
            self._probing_now.discard(wid)
            if wid not in self._isolated_nodes:
                continue

            nm = metrics.node_metrics.get(wid)
            has_data = nm is not None and len(nm.departure_intervals) >= min_intervals

            # Severity from probe data (no confirmation needed)
            probe_sev = 0.0
            if has_data:
                probe_sev = self._compute_probe_severity(nm.departure_intervals)

            if has_data and probe_sev < self.PROBE_THETA:
                # Probe says healthy
                self._recovery_count[wid] = self._recovery_count.get(wid, 0) + 1
                if self._recovery_count[wid] >= self.RECOVERY_CONFIRM:
                    # Confirmed recovered — reintegrate with probation (fix #6, #8)
                    weights[wid] = self.PROBATION_WEIGHT
                    excluded[wid] = False
                    self._isolated_nodes.discard(wid)
                    self._isolation_epoch.pop(wid, None)
                    self._recovery_count.pop(wid, None)
                    self._probe_epoch.pop(wid, None)
                    self.aimd.reset_weight(wid, self.PROBATION_WEIGHT)
                    # Reset detector state for clean re-detection (fix #6)
                    self.detector._consecutive[wid] = 0
                    # Enter probation period
                    self._probation_nodes[wid] = self._current_epoch + self.PROBATION_EPOCHS
                    continue
            elif has_data:
                # Has data but still faulted — reset recovery counter
                self._recovery_count[wid] = 0
            # else: insufficient data — no-op, keep recovery_count as-is

            # Schedule next probe and keep isolated
            self._probe_epoch[wid] = self._current_epoch + self.PROBE_INTERVAL
            weights[wid] = 0.0
            excluded[wid] = True

        # Step 2: Set probe weight for AT MOST ONE node due to probe next epoch.
        # Probing multiple faulted nodes simultaneously amplifies P99 impact.
        # Use round-robin by sorting on next_probe time to ensure fairness.
        probe_candidates = []
        for wid in self._isolated_nodes:
            if wid in self._probing_now:
                continue
            next_probe = self._probe_epoch.get(wid, self._current_epoch + self.MIN_HOLD_EPOCHS)
            if next_probe <= self._current_epoch:
                probe_candidates.append((next_probe, wid))

        if probe_candidates:
            # Pick the node that has been waiting longest (earliest scheduled)
            probe_candidates.sort()
            _, wid = probe_candidates[0]
            weights[wid] = self.PROBE_WEIGHT
            excluded[wid] = False
            self._probing_now.add(wid)

        return jnp.array(weights), jnp.array(excluded)
