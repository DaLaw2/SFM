"""Fault injection module for slow-fault simulation.

Provides severity utilities, fault pattern models, and the FaultInjector
SimPy process for applying configurable slowdown factors to worker nodes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


# ---------------------------------------------------------------------------
# Severity utilities
# ---------------------------------------------------------------------------

def severity_score(slowdown: float) -> float:
    """Convert slowdown factor to severity score in [0, 1).

    severity = 1 - 1/s
      - s=1.0  -> 0.0   (normal)
      - s=2.0  -> 0.5   (50% capacity)
      - s=10.0 -> 0.9   (10% capacity)
    """
    if slowdown <= 1.0:
        return 0.0
    return 1.0 - (1.0 / slowdown)


def slowdown_from_severity(severity: float) -> float:
    """Convert severity score back to slowdown factor.

    Inverse of severity_score:  s = 1 / (1 - severity)
    """
    if severity <= 0.0:
        return 1.0
    return 1.0 / (1.0 - severity)


# ---------------------------------------------------------------------------
# Fault patterns (abstract base + 4 implementations)
# ---------------------------------------------------------------------------

class FaultPattern(ABC):
    """Abstract base for temporal fault patterns."""

    @abstractmethod
    def get_slowdown(self, t: float, onset: float) -> float:
        """Return the slowdown factor at time *t*, given fault *onset* time.

        Must return >= 1.0.
        """


class PermanentFault(FaultPattern):
    """Constant slowdown after onset: s(t) = s_const for t > onset."""

    def __init__(self, slowdown: float) -> None:
        if slowdown < 1.0:
            raise ValueError("slowdown must be >= 1.0")
        self._slowdown = slowdown

    def get_slowdown(self, t: float, onset: float) -> float:
        if t <= onset:
            return 1.0
        return self._slowdown


class FluctuatingFault(FaultPattern):
    """Alternates between 1.0 and *s_peak* with configurable duty cycle.

    The fault is active (s_peak) for *d_on* time units, then inactive (1.0)
    for *d_off* time units, repeating.
    """

    def __init__(self, s_peak: float, d_on: float, d_off: float) -> None:
        if s_peak < 1.0:
            raise ValueError("s_peak must be >= 1.0")
        if d_on <= 0 or d_off <= 0:
            raise ValueError("d_on and d_off must be positive")
        self._s_peak = s_peak
        self._d_on = d_on
        self._d_off = d_off

    def get_slowdown(self, t: float, onset: float) -> float:
        if t <= onset:
            return 1.0
        elapsed = t - onset
        cycle = self._d_on + self._d_off
        phase = elapsed % cycle
        if phase < self._d_on:
            return self._s_peak
        return 1.0


class ProgressiveFault(FaultPattern):
    """Linearly increasing slowdown: s(t) = 1.0 + beta * (t - onset), capped at s_max.

    Models thermal throttling where degradation worsens over time.
    """

    def __init__(self, beta: float, s_max: float = 10.0) -> None:
        if beta < 0:
            raise ValueError("beta must be non-negative")
        if s_max < 1.0:
            raise ValueError("s_max must be >= 1.0")
        self._beta = beta
        self._s_max = s_max

    def get_slowdown(self, t: float, onset: float) -> float:
        if t <= onset:
            return 1.0
        raw = 1.0 + self._beta * (t - onset)
        return min(raw, self._s_max)


class IntermittentFault(FaultPattern):
    """Random flips between 1.0 and *s_peak* with probability *p_flip* per call.

    Uses a numpy Generator for reproducible randomness.  The internal state
    tracks whether the fault is currently active.
    """

    def __init__(self, s_peak: float, p_flip: float,
                 rng: np.random.Generator) -> None:
        if s_peak < 1.0:
            raise ValueError("s_peak must be >= 1.0")
        if not 0.0 <= p_flip <= 1.0:
            raise ValueError("p_flip must be in [0, 1]")
        self._s_peak = s_peak
        self._p_flip = p_flip
        self._rng = rng
        self._active = False

    def get_slowdown(self, t: float, onset: float) -> float:
        if t <= onset:
            self._active = False
            return 1.0
        if self._rng.random() < self._p_flip:
            self._active = not self._active
        return self._s_peak if self._active else 1.0


# ---------------------------------------------------------------------------
# Fault scenario dataclass
# ---------------------------------------------------------------------------

@dataclass
class FaultScenario:
    """Describes a fault to inject on specific nodes.

    Attributes:
        node_indices: Worker indices affected by this fault.
        pattern: The temporal fault pattern to apply.
        onset_time: Simulation time when the fault begins.
        duration: How long the fault lasts (None = permanent).
    """
    node_indices: list[int]
    pattern: FaultPattern
    onset_time: float
    duration: float | None = None
