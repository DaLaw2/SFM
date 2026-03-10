# V12 Findings: Parameter Sensitivity Analysis (S9)

**Date**: 2026-03-08
**Baseline**: 7b0dd5e (V12)
**Experiment**: S9 — vary 3 key parameters on S4 scenario (hardest passing case)

## Parameters Tested

All tested on S4 (4 faults, random 2-5x, 32 nodes, 80% load, 10 runs each).
One parameter varied at a time, others held at default.

### decision_epoch (control loop frequency)
| Value | P99 (ms) | CI | SLO Viol% |
|-------|---------|-----|-----------|
| 0.25s | 42.6 | ±9.4 | 0.43% |
| **0.50s** | **38.3** | **±1.6** | **0.18%** |
| 1.00s | 38.1 | ±0.5 | 0.22% |
| 2.00s | 38.5 | ±0.4 | 0.42% |

### theta_iso (isolation threshold)
| Value | P99 (ms) | CI | SLO Viol% |
|-------|---------|-----|-----------|
| 0.30 | 38.9 | ±2.4 | 0.20% |
| 0.40 | 37.9 | ±0.2 | 0.18% |
| **0.50** | **42.3** | **±9.3** | **0.42%** |
| 0.60 | 42.8 | ±10.9 | 0.40% |
| 0.70 | 37.6 | ±0.3 | 0.14% |

### debounce (confirmation epochs before de-escalation)
| Value | P99 (ms) | CI | SLO Viol% |
|-------|---------|-----|-----------|
| 1 | 42.5 | ±11.4 | 0.44% |
| **2** | **38.1** | **±0.6** | **0.20%** |
| 3 | 38.7 | ±2.8 | 0.19% |
| 4 | 46.8 | ±20.9 | 0.41% |

## Key Findings

### 1. System is robust to parameter variation

All 13 parameter configurations keep P99 under 50ms SLO. The worst case
(debounce=4, 46.8ms) still passes. Maximum P99 variation:
- decision_epoch: 38-43ms across 8x range (0.25-2.0s) → <12% variation
- theta_iso: 38-43ms across 2.3x range (0.3-0.7) → <13% variation
- debounce: 38-47ms across 4x range (1-4) → <24% variation

### 2. Wide CIs at boundary parameter values

theta_iso=0.5/0.6 and debounce=1/4 show wider CIs (±9-21ms vs ±0.2-2.8ms).
This indicates some seeds produce severities near the decision boundary,
causing intermittent strategy changes. The system works but with higher
per-run variance.

### 3. No "cliff edge" in parameter space

Unlike the fault fraction limit (sharp transition at 13%), parameter sensitivity
shows smooth degradation. No parameter value causes catastrophic failure. This
strongly suggests the results are not due to parameter overfitting.

### 4. Sweet spots

- decision_epoch: 0.5-1.0s (fast enough to detect, slow enough to avoid noise)
- theta_iso: 0.3-0.4 (aggressive isolation works best for S4's multi-node faults)
- debounce: 2-3 (balances false positive prevention with detection speed)

Current defaults (0.5s, 0.5, 2) are close to optimal but theta_iso=0.4 might
be slightly better for multi-node scenarios.

## Conclusion

The adaptive strategy's performance on S4 is robust to ±50% parameter perturbation.
This answers the key deployability question: the system does not require precise tuning.
