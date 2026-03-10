# DR-008: Detector Noise Filtering and Cascade Prevention

**Date**: 2026-03-07
**Status**: Decided

## Context

First round of experiments showed adaptive strategy performing worst across all scenarios — even worse than no mitigation. Root cause: three cascading bugs.

## Problem Chain

1. **Detector noise**: Peer comparison using median means ~50% of nodes always have latency > median, producing non-zero severity even without faults.
2. **False SPECULATE triggers**: With theta_spec = 0.1, noise-induced severity easily exceeds threshold.
3. **AIMD cascade**: Weight normalization across ALL nodes (including healthy ones) redistributes load, increasing latency on other nodes, triggering more false positives — snowball effect.

## Fixes Applied

1. **Detector**: Added `MIN_SEVERITY = 0.05` floor and `MIN_LATENCY_RATIO = 1.2` (node must be 20% slower than median to register any severity).
2. **AIMD**: Removed global weight normalization. AIMD only manages SHED node weights.
3. **Control loop**: Only updates balancer weights for SHED/ISOLATE nodes; NORMAL/SPECULATE nodes keep default weight.
4. **Speculation**: Added spare capacity guard via `hedge_remaining` flag.

## Validation

- No fault + mitigation ON: P99 = 27.4ms (was 9,531ms before fix)
- Fault s=3.0 + mitigation ON: P99 = 28.4ms vs 59.5ms without mitigation (52% improvement)
