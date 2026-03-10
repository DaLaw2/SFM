"""Test / demonstration script for the fault injection module.

Run with:  python -m simulator.fault.test_fault
"""

from __future__ import annotations

import numpy as np
import simpy

from simulator.fault import (
    FaultScenario,
    FluctuatingFault,
    IntermittentFault,
    PermanentFault,
    ProgressiveFault,
    severity_score,
    slowdown_from_severity,
)
from simulator.fault.injector import FaultInjector


# ---------------------------------------------------------------------------
# 1. Severity utilities round-trip
# ---------------------------------------------------------------------------

def test_severity_utils() -> None:
    print("=== Severity utilities ===")
    for s in [1.0, 1.5, 2.0, 3.0, 5.0, 10.0]:
        sev = severity_score(s)
        s_back = slowdown_from_severity(sev)
        ok = "OK" if abs(s_back - s) < 1e-9 else "FAIL"
        print(f"  slowdown={s:5.1f}  severity={sev:.4f}  round-trip={s_back:.4f}  [{ok}]")

    # Edge cases
    assert severity_score(0.5) == 0.0, "slowdown < 1 should give 0"
    assert slowdown_from_severity(-0.1) == 1.0, "negative severity should give 1"
    print("  Edge cases passed.\n")


# ---------------------------------------------------------------------------
# 2. Fault pattern sampling
# ---------------------------------------------------------------------------

def test_patterns() -> None:
    print("=== Fault patterns ===")
    onset = 5.0

    # PermanentFault
    pf = PermanentFault(slowdown=3.0)
    print("  PermanentFault(3.0):")
    for t in [0, 4.9, 5.0, 5.01, 10, 100]:
        print(f"    t={t:6.2f}  s={pf.get_slowdown(t, onset):.2f}")

    # FluctuatingFault
    ff = FluctuatingFault(s_peak=4.0, d_on=2.0, d_off=3.0)
    print("  FluctuatingFault(s_peak=4.0, d_on=2, d_off=3):")
    for t in [4.0, 5.0, 5.5, 6.9, 7.0, 8.0, 9.9, 10.0, 11.5]:
        print(f"    t={t:6.2f}  s={ff.get_slowdown(t, onset):.2f}")

    # ProgressiveFault
    prog = ProgressiveFault(beta=0.1, s_max=5.0)
    print("  ProgressiveFault(beta=0.1, s_max=5.0):")
    for t in [4.0, 5.0, 10.0, 20.0, 50.0, 100.0]:
        print(f"    t={t:6.2f}  s={prog.get_slowdown(t, onset):.2f}")

    # IntermittentFault
    rng = np.random.default_rng(42)
    intm = IntermittentFault(s_peak=3.0, p_flip=0.3, rng=rng)
    print("  IntermittentFault(s_peak=3.0, p_flip=0.3, seed=42):")
    for t in [4.0, 6.0, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8]:
        print(f"    t={t:6.2f}  s={intm.get_slowdown(t, onset):.2f}")
    print()


# ---------------------------------------------------------------------------
# 3. FaultInjector integration with SimPy
# ---------------------------------------------------------------------------

class MockWorker:
    """Minimal worker stub with a slowdown_factor attribute."""
    def __init__(self, idx: int) -> None:
        self.idx = idx
        self.slowdown_factor: float = 1.0

    def __repr__(self) -> str:
        return f"Worker({self.idx}, sf={self.slowdown_factor:.2f})"


def test_injector() -> None:
    print("=== FaultInjector (SimPy integration) ===")
    env = simpy.Environment()
    workers = [MockWorker(i) for i in range(4)]

    scenarios = [
        FaultScenario(
            node_indices=[0],
            pattern=PermanentFault(slowdown=2.0),
            onset_time=1.0,
        ),
        FaultScenario(
            node_indices=[1],
            pattern=ProgressiveFault(beta=0.5, s_max=5.0),
            onset_time=2.0,
            duration=6.0,  # active from t=2 to t=8
        ),
        FaultScenario(
            node_indices=[2, 3],
            pattern=FluctuatingFault(s_peak=3.0, d_on=1.0, d_off=1.0),
            onset_time=0.5,
        ),
    ]

    injector = FaultInjector(env, workers, scenarios, update_interval=0.5)
    env.process(injector.run())

    # Observer process that prints state at each step
    def observer():
        for _ in range(20):
            yield env.timeout(0.5)
            factors = [f"{w.slowdown_factor:.2f}" for w in workers]
            print(f"  t={env.now:5.1f}  slowdowns={factors}")

    env.process(observer())
    env.run(until=10.0)

    # After duration expires for scenario on worker 1, it should reset
    print(f"\n  Worker 1 at t=10: slowdown={workers[1].slowdown_factor:.2f} "
          f"(expect 1.00 -- duration expired)")
    assert workers[1].slowdown_factor == 1.0, "Worker 1 should be reset after duration"
    print("  Duration-based reset: OK\n")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_severity_utils()
    test_patterns()
    test_injector()
    print("All tests passed.")
