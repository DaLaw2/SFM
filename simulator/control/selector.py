from __future__ import annotations

from dataclasses import dataclass, field

from simulator.config import StrategyConfig
from simulator.control import Strategy


@dataclass
class SelectorOutput:
    strategy_map: dict[int, Strategy]
    weight_map: dict[int, float]
    hedge_remaining: dict[int, bool] = field(default_factory=dict)


class StrategySelector:
    def __init__(self, node_ids: list[int], config: StrategyConfig | None = None) -> None:
        self.cfg = config or StrategyConfig()
        self._node_ids = node_ids
        self.strategy_map: dict[int, Strategy] = {
            wid: Strategy.NORMAL for wid in node_ids
        }
        self._de_escalation_count: dict[int, int] = {wid: 0 for wid in node_ids}

    def select(
        self,
        severities: dict[int, float],
        slo_dist: float,
        spare: float,
    ) -> SelectorOutput:
        urgency = max(0.0, 1.0 - slo_dist)

        # M2: Load-aware theta_spec — raise the speculation threshold when
        # spare capacity is low, preventing hedges from overloading healthy
        # workers at high utilization.  Factor ranges from 1.0 (plenty of
        # spare) to 3.0 (no spare at all).
        load_factor = 1.0 + 2.0 * max(0.0, 1.0 - spare / max(self.cfg.spare_min, 0.01))
        t_spec = self.cfg.theta_spec * load_factor * (1.0 - 0.5 * urgency)
        t_shed = self.cfg.theta_shed * (1.0 - 0.4 * urgency)
        t_iso = self.cfg.theta_iso * (1.0 - 0.3 * urgency)

        thresholds = {
            Strategy.NORMAL: 0.0,
            Strategy.SPECULATE: t_spec,
            Strategy.SHED: t_shed,
            Strategy.ISOLATE: t_iso,
        }

        new_map: dict[int, Strategy] = {}

        for wid, sev in severities.items():
            cur = self.strategy_map.get(wid, Strategy.NORMAL)

            if sev >= t_iso:
                target = Strategy.ISOLATE
            elif sev >= t_shed:
                target = Strategy.SHED
            elif sev >= t_spec:
                # M4: Cost-benefit gate — only speculate if there's enough
                # spare capacity; otherwise skip to SHED (which doesn't add
                # load) or stay NORMAL if severity is marginal.
                if spare > self.cfg.spare_min:
                    target = Strategy.SPECULATE
                elif sev >= t_shed * 0.8:
                    target = Strategy.SHED
                else:
                    target = Strategy.NORMAL
            else:
                target = Strategy.NORMAL

            if target > cur:
                new_map[wid] = target
                self._de_escalation_count[wid] = 0
            elif target < cur:
                if target == Strategy.NORMAL:
                    check_threshold = t_spec
                else:
                    check_threshold = thresholds.get(target, 0.0)
                if sev < check_threshold - self.cfg.hysteresis:
                    self._de_escalation_count[wid] = self._de_escalation_count.get(wid, 0) + 1
                    if self._de_escalation_count[wid] >= self.cfg.debounce:
                        de_esc = _de_escalate(cur)
                        # Skip SPECULATE when no spare (M4 consistency)
                        if de_esc == Strategy.SPECULATE and spare <= self.cfg.spare_min:
                            de_esc = Strategy.NORMAL
                        new_map[wid] = de_esc
                        self._de_escalation_count[wid] = 0
                    else:
                        new_map[wid] = cur
                else:
                    self._de_escalation_count[wid] = 0
                    new_map[wid] = cur
            else:
                new_map[wid] = cur
                self._de_escalation_count[wid] = 0

            # Emergency override — respect M4: skip SPECULATE when no spare
            if slo_dist < 0 and sev > t_spec:
                escalated = _escalate(cur)
                if escalated == Strategy.SPECULATE and spare <= self.cfg.spare_min:
                    escalated = Strategy.SHED
                if escalated > new_map[wid]:
                    new_map[wid] = escalated

        # G2: Two-layer isolation budget.
        #
        # Layer 1 (severity-aware): A node with severity 0.8 (5x slowdown)
        # only contributes 0.2 effective capacity, so isolating it costs
        # 0.2, not 1.0.  This allows full isolation of high-severity faults.
        #
        # Layer 2 (absolute capacity): Hard check that remaining node count
        # can handle the load.  Prevents the severity-aware formula from
        # approving isolation that causes overload (e.g., 8 nodes at 3x —
        # severity-aware says cost is 2.7, but actual remaining capacity
        # is 24/32 = 75%, insufficient for 80% load).
        n_total = len(self._node_ids)
        isolated_wids = [wid for wid, s in new_map.items() if s == Strategy.ISOLATE]
        if isolated_wids:
            isolated_wids.sort(key=lambda w: severities.get(w, 0.0), reverse=True)

            # Layer 2: absolute capacity — remaining nodes must handle load
            current_load = (1.0 - spare) * n_total  # load in node-equivalents
            min_remaining = current_load / 0.92  # nodes needed to stay under 92%

            # Layer 1: severity-aware cost
            effective_cap_loss = sum(
                1.0 - severities.get(wid, 0.0) for wid in isolated_wids
            )
            effective_remaining = n_total - effective_cap_loss

            if effective_remaining <= 0:
                for wid in isolated_wids:
                    new_map[wid] = Strategy.SHED
            else:
                remaining_rho = (1.0 - spare) * n_total / effective_remaining
                n_remaining = n_total - len(isolated_wids)  # absolute count

                if remaining_rho > 0.92 or n_remaining < min_remaining:
                    # Greedy: keep highest-severity nodes isolated first
                    current_rho = 1.0 - spare
                    cum_loss = 0.0
                    n_kept = 0
                    max_k = 0
                    for wid in isolated_wids:
                        node_cost = 1.0 - severities.get(wid, 0.0)
                        trial_eff_remaining = n_total - cum_loss - node_cost
                        trial_abs_remaining = n_total - n_kept - 1
                        # Both layers must pass
                        sev_ok = (trial_eff_remaining > 0 and
                                  current_rho * n_total / trial_eff_remaining <= 0.92)
                        abs_ok = trial_abs_remaining >= min_remaining
                        if sev_ok and abs_ok:
                            cum_loss += node_cost
                            n_kept += 1
                            max_k += 1
                        else:
                            break
                    for wid in isolated_wids[max_k:]:
                        new_map[wid] = Strategy.SHED

        self.strategy_map = new_map

        weight_map: dict[int, float] = {}
        hedge_remaining: dict[int, bool] = {}

        # SHED weight damping — at high load, blend SHED weights toward 1.0
        # to avoid capacity collapse, but keep a minimum factor (0.3) so
        # SHED retains meaningful effect even under high load.
        spare_factor = min(1.0, max(0.3, (spare - 0.08) / 0.15))

        for wid in severities:
            strat = new_map.get(wid, Strategy.NORMAL)
            if strat == Strategy.ISOLATE:
                weight_map[wid] = 0.0
            elif strat == Strategy.SHED:
                raw_w = max(self.cfg.w_min, 1.0 - severities.get(wid, 0.0))
                weight_map[wid] = raw_w * spare_factor + 1.0 * (1.0 - spare_factor)
            else:
                weight_map[wid] = 1.0

        # V6-final: SHED capacity guard — if total weight reduction would
        # push healthy nodes above safe utilization, scale back SHED weights.
        # Extends G2 isolation budget pattern to SHED.
        shed_wids = [wid for wid, s in new_map.items() if s == Strategy.SHED]
        if shed_wids:
            total_weight = sum(weight_map.get(wid, 1.0) for wid in severities)
            n_normal = n_total - len(shed_wids) - len(
                [w for w, s in new_map.items() if s == Strategy.ISOLATE]
            )
            if n_normal > 0 and total_weight > 0:
                current_rho = 1.0 - spare
                rho_healthy = current_rho * n_total / total_weight
                if rho_healthy > 0.88:
                    # Scale back: find weight floor that keeps rho_healthy <= 0.88
                    # rho_healthy = current_rho * n_total / total_weight <= 0.88
                    # total_weight >= current_rho * n_total / 0.88
                    min_total_weight = current_rho * n_total / 0.88
                    current_shed_deficit = n_total - total_weight  # how much weight was removed
                    if current_shed_deficit > 0:
                        max_deficit = n_total - min_total_weight
                        scale = max(0.0, min(1.0, max_deficit / current_shed_deficit))
                        for wid in shed_wids:
                            old_w = weight_map[wid]
                            weight_map[wid] = 1.0 - scale * (1.0 - old_w)

        return SelectorOutput(
            strategy_map=new_map,
            weight_map=weight_map,
            hedge_remaining=hedge_remaining,
        )


def _escalate(s: Strategy) -> Strategy:
    if s == Strategy.NORMAL:
        return Strategy.SPECULATE
    if s == Strategy.SPECULATE:
        return Strategy.SHED
    if s == Strategy.SHED:
        return Strategy.ISOLATE
    return Strategy.ISOLATE


def _de_escalate(s: Strategy) -> Strategy:
    if s == Strategy.ISOLATE:
        return Strategy.SHED
    if s == Strategy.SHED:
        return Strategy.SPECULATE
    if s == Strategy.SPECULATE:
        return Strategy.NORMAL
    return Strategy.NORMAL
