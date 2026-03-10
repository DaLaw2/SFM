# DR-005: Strategy Composition

**Date**: 2026-03-07
**Status**: Decided

## Context

Should strategies be composable (e.g., SHED + SPECULATE simultaneously on one node)?

## Options

1. **Mutual exclusion** - one strategy per node, simple state machine
2. **SHED with optional hedging** - SHED strategy has a `hedge_remaining` parameter
3. **Bitmask composition** - arbitrary strategy combinations

## Decision

**Option 2: Keep state machine simple, add `hedge_remaining` parameter to SHED.**

## Rationale

- At moderate severity with tight SLO, shedding + hedging on remaining requests gives best of both worlds
- Keeps NORMAL -> SPECULATE -> SHED -> ISOLATE state machine intact
- Avoids state space explosion of bitmask approach
- For a simulation paper, simplicity in design is a strength
- The combined effect is captured without architectural complexity

## Implementation

SHED strategy parameters gain:
- `hedge_remaining: bool` (default: true when `spare > SPARE_MIN`)
- When enabled, requests still routed to the slow node also get a hedged copy
