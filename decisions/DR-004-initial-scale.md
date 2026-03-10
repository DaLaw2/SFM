# DR-004: Initial Cluster Scale

**Date**: 2026-03-07
**Status**: Decided

## Context

Choose the number of worker nodes for initial experiments.

## Options

1. **8 nodes** - minimal
2. **16 nodes** - moderate, typical small inference cluster
3. **64 nodes** - large, closer to production scale

## Decision

**Option 2: 16 nodes for initial experiments.**

## Rationale

- 16 nodes is enough to demonstrate multi-node fault scenarios (e.g., 4/16 nodes failing = 25%)
- Small enough for fast iteration during development
- Large enough that single-node faults don't trivially dominate system behavior
- Start simple, scale to 64 later for scalability analysis

## Follow-up

- [ ] Add 64-node experiments for scalability section of paper
- [ ] Consider 128 nodes if reviewer requests larger scale
