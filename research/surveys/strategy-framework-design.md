# Survey: Adaptive Strategy Selection for Slow Fault Mitigation

## 1. Problem Formalization

### 1.1 System Model

Consider a distributed inference serving system with:

- **N worker nodes** `W = {w_1, w_2, ..., w_N}`, each with baseline processing capacity `C_i` (requests/sec)
- **Request stream** `R` arriving at rate `lambda` (requests/sec) dispatched by a centralized load balancer
- **Per-request processing time** `T_i(t)` on node `w_i` at time `t`; under normal conditions, `T_i(t) ~ T_base_i` (deterministic for DNN inference, per Clockwork's observation)
- **SLO contract** defined as a latency percentile target: `P(latency <= L_target) >= 1 - alpha`, where `L_target` is the target latency and `alpha` is the allowed violation rate (e.g., P99 <= 200ms means `alpha = 0.01`)

### 1.2 Slow Fault Model

A slow fault on node `w_i` is modeled as a multiplicative slowdown factor `s_i(t) >= 1.0`:

```
T_i^fault(t) = s_i(t) * T_base_i
```

where:
- `s_i(t) = 1.0` denotes normal operation
- `s_i(t) = 2.0` denotes a node operating at half its normal speed
- `s_i(t) -> infinity` approaches a crash failure

**Temporal patterns** (from Gunawi et al., FAST 2018):
1. **Permanent**: `s_i(t) = s_const` for `t > t_onset`
2. **Fluctuating**: `s_i(t)` alternates between `1.0` and `s_peak` with configurable duty cycle `(d_on, d_off)`
3. **Progressive**: `s_i(t) = 1.0 + beta * (t - t_onset)` for `t > t_onset`, modeling thermal throttling (per TAPAS, ASPLOS 2025)
4. **Intermittent**: `s_i(t)` drawn from `{1.0, s_peak}` with transition probability `p_flip` per time step

**Severity score** (continuous, inspired by Perseus slowdown ratio):

```
severity_i(t) = 1 - (1 / s_i(t))    in [0, 1)
```

- `severity = 0` -> normal
- `severity = 0.5` -> node at 50% capacity (s=2.0)
- `severity = 0.9` -> node at 10% capacity (s=10.0)

### 1.3 Danger Zone

Following ADR (NSDI 2025), we define the danger zone as the severity range `[d_lo, d_hi]` where system-level performance degrades non-linearly:

```
perf_degradation(severity) = {
    mild (< 10%)                   if severity < d_lo
    cliff (10% -> 50%+ rapidly)    if d_lo <= severity <= d_hi
    severe (> 50%)                 if severity > d_hi
}
```

The danger zone boundaries `d_lo, d_hi` are workload-dependent and must be discovered empirically or estimated via online probing. ADR's empirical data shows these ranges are narrow (e.g., Cassandra read-only: 0.2--3ms added latency; write-only: 0.1--1ms).

### 1.4 Objective Function

Maximize system throughput subject to latency SLO compliance:

```
maximize:   Throughput = sum_{i=1}^{N} lambda_i(t)
subject to: Percentile(latency, 1-alpha) <= L_target
            lambda_i(t) >= 0  for all i
            sum_{i=1}^{N} lambda_i(t) = lambda  (all requests served)
```

where `lambda_i(t)` is the request rate assigned to node `w_i`.

When the constraint cannot be satisfied (insufficient healthy capacity), the secondary objective is to minimize the SLO violation rate.

---

## 2. Strategy Space

### 2.1 Strategy S1: Speculative Execution (Hedging)

**Mechanism**: For requests routed to a suspected-slow node, simultaneously dispatch a redundant copy to a healthy node. Return whichever response arrives first; cancel the other.

**Parameters**:
| Parameter | Symbol | Description | Default |
|-----------|--------|-------------|---------|
| Trigger threshold | `theta_spec` | Minimum severity score to trigger speculation | 0.1 |
| Replica count | `k` | Number of redundant copies (1 = hedged request) | 1 |
| Hedging delay | `delta_h` | Delay before sending replica (0 = immediate) | P50 latency |
| Cancellation policy | -- | Cancel replicas on first response | Eager cancel |
| Capacity guard | `c_min` | Minimum spare capacity ratio to allow speculation | 0.2 |

**When appropriate**: Low severity (`severity < 0.3`), sufficient spare capacity (`spare_ratio > c_min`). The cost is `k * request_cost` additional compute per speculated request. Dean and Barroso (CACM 2013) showed that hedging after a brief delay (e.g., P95 latency) can reduce 99.9th-percentile latency from 1,800ms to 74ms with only 2% additional load.

**Cost model**:
```
overhead_spec = k * (fraction_of_requests_speculated) * avg_request_cost
```

### 2.2 Strategy S2: Load Shedding (Weight Reduction)

**Mechanism**: Reduce the fraction of traffic routed to the slow node, redistributing to healthy nodes proportionally to their available capacity.

**Parameters**:
| Parameter | Symbol | Description | Default |
|-----------|--------|-------------|---------|
| Weight reduction factor | `r` | Multiplicative reduction to node weight | AIMD-computed |
| Minimum weight | `w_min` | Minimum traffic share before isolation | 0.05 |
| AIMD additive increase | `a` | Weight increase per stable period | 0.05 |
| AIMD multiplicative decrease | `m` | Weight multiplier on degradation | 0.5 |
| Rebalance interval | `tau_r` | How often to adjust weights | 1 second |

**When appropriate**: Moderate severity (`0.2 <= severity < 0.7`), the node is still useful but not at full capacity. Preserves partial throughput from the degraded node. Inspired by DAGOR (WeChat, SoCC 2018) and Zalando's AIMD-based load shedding deployed in production for 6+ months.

**Weight update algorithm (AIMD)**:
```
On each rebalance interval:
  if node_i is slow AND slo_distance is shrinking:
    weight_i = max(weight_i * m, w_min)            # multiplicative decrease
  elif node_i was slow AND metrics improving:
    weight_i = min(weight_i + a, weight_baseline_i)  # additive increase

  Normalize: weight_j = weight_j / sum(all weights)  for all j
```

**Cost model**:
```
throughput_loss = (1 - weight_i / weight_baseline_i) * C_i  (wasted capacity on slow node)
pressure_increase = redistributed_load / sum(healthy_capacity)
```

### 2.3 Strategy S3: Isolation (Quarantine)

**Mechanism**: Remove the slow node from the active pool entirely. All traffic is redistributed to remaining healthy nodes. The isolated node enters a recovery probe cycle.

**Parameters**:
| Parameter | Symbol | Description | Default |
|-----------|--------|-------------|---------|
| Isolation threshold | `theta_iso` | Severity score triggering isolation | 0.7 |
| Probe interval | `tau_p` | Time between recovery probes | 30 seconds |
| Probe request count | `n_p` | Number of test requests per probe | 5 |
| Recovery threshold | `theta_rec` | Severity below which to reintegrate | 0.15 |
| Reintegration ramp | -- | AIMD-style gradual weight increase | Same as S2 |

**When appropriate**: High severity (`severity >= 0.7`), or when SLO is being violated and the slow node is identified as the cause. Incurs total loss of the node's capacity. This mirrors IASO's approach (ATC 2019) but adds a graduated recovery path rather than binary reboot/shutdown.

**Recovery probe cycle**:
```
while node_i is isolated:
    wait(tau_p)
    send n_p probe requests to node_i
    measure probe_severity from response times
    if probe_severity < theta_rec:
        reintegrate node_i with weight = w_min
        transition to S2 (load shedding with AIMD recovery)
        break
```

### 2.4 Strategy Composition and Ordering

Strategies are not mutually exclusive across nodes. At any time, the system may apply different strategies to different nodes:

```
strategy_map: W -> {NORMAL, SPECULATE, SHED, ISOLATE}
```

For a single node, strategies are ordered by escalation severity:

```
NORMAL -> SPECULATE -> SHED -> ISOLATE -> (recovery probe) -> SHED -> NORMAL
```

The escalation is monotonically increasing in aggressiveness; de-escalation always follows the reverse path (never jumps from ISOLATE directly to NORMAL).

---

## 3. Decision Logic

### 3.1 Input Signals

The strategy selector operates on three primary signals, computed per monitoring interval `tau` (default: 500ms):

1. **Fault severity score** `severity_i(t)`: Per-node severity from the detection layer (Section 1.2). Derived from the slowdown ratio `s_i(t)` as observed via peer comparison or regression (Perseus-style).

2. **SLO distance** `slo_dist(t)`: System-level margin to SLO violation.
   ```
   slo_dist(t) = (L_target - P99_observed(t)) / L_target    in (-inf, 1]
   ```
   - `slo_dist > 0`: within SLO (positive margin)
   - `slo_dist = 0`: exactly at SLO boundary
   - `slo_dist < 0`: SLO violated

3. **Spare capacity ratio** `spare(t)`: Fraction of total healthy capacity not currently utilized.
   ```
   spare(t) = 1 - (lambda / sum_{j: healthy} C_j)
   ```
   - `spare > 0`: system has headroom
   - `spare <= 0`: system is at or over capacity

### 3.2 Adaptive Thresholds

Static thresholds fail because the danger zone shifts with workload (ADR's key finding). We use adaptive thresholds that tighten near the danger zone:

```
urgency(t) = max(0, 1 - slo_dist(t))
```

When `urgency` is high (close to or past SLO), thresholds shift to trigger more aggressive strategies earlier:

```
theta_spec_adaptive = theta_spec * (1 - 0.5 * urgency)
theta_iso_adaptive  = theta_iso  * (1 - 0.3 * urgency)
```

This means: when the system is far from SLO violation, thresholds are lenient (tolerate more slowdown before acting). When close to SLO violation, thresholds tighten (act on smaller slowdowns).

### 3.3 Decision Algorithm (Pseudocode)

```
Algorithm: AdaptiveStrategySelector

Input:
  severity[1..N]          -- per-node severity scores
  slo_dist                -- system-level SLO distance
  spare                   -- spare capacity ratio
  current_strategy[1..N]  -- current strategy per node

Output:
  new_strategy[1..N]      -- updated strategy per node

Constants:
  THETA_SPEC = 0.1    -- base speculation threshold
  THETA_SHED = 0.3    -- base load-shedding threshold
  THETA_ISO  = 0.7    -- base isolation threshold
  SPARE_MIN  = 0.15   -- minimum spare capacity for speculation
  HYSTERESIS = 0.05   -- hysteresis band to prevent oscillation
  DEBOUNCE   = 2      -- consecutive intervals required for de-escalation

State:
  de_escalation_count[1..N] = 0  -- tracks consecutive stable intervals

Procedure SelectStrategies():
  urgency = max(0, 1 - slo_dist)

  // Adapt thresholds based on SLO urgency
  t_spec = THETA_SPEC * (1 - 0.5 * urgency)
  t_shed = THETA_SHED * (1 - 0.4 * urgency)
  t_iso  = THETA_ISO  * (1 - 0.3 * urgency)

  for each node i in 1..N:
    sev = severity[i]
    cur = current_strategy[i]

    // --- Determine target strategy based on severity ---
    if sev >= t_iso:
      target = ISOLATE
    elif sev >= t_shed:
      target = SHED
    elif sev >= t_spec:
      if spare > SPARE_MIN:
        target = SPECULATE
      else:
        target = SHED    // no spare capacity; skip to shedding
    else:
      target = NORMAL

    // --- Apply escalation/de-escalation rules ---
    if target > cur:
      // Escalation: apply immediately
      new_strategy[i] = target
      de_escalation_count[i] = 0

    elif target < cur:
      // De-escalation: require sustained improvement (debounce)
      // Also apply hysteresis: severity must be below threshold - HYSTERESIS
      if sev < threshold_for(target) - HYSTERESIS:
        de_escalation_count[i] += 1
        if de_escalation_count[i] >= DEBOUNCE:
          new_strategy[i] = de_escalate_one_level(cur)  // step down one level
          de_escalation_count[i] = 0
        else:
          new_strategy[i] = cur  // hold current strategy
      else:
        de_escalation_count[i] = 0
        new_strategy[i] = cur

    else:
      new_strategy[i] = cur
      de_escalation_count[i] = 0

    // --- Emergency override: SLO violated ---
    if slo_dist < 0 AND sev > t_spec:
      new_strategy[i] = max(new_strategy[i], escalate_one_level(cur))

  return new_strategy

Function threshold_for(strategy):
  // Returns the threshold below which this strategy is appropriate
  if strategy == NORMAL:    return 0
  if strategy == SPECULATE: return t_spec
  if strategy == SHED:      return t_shed
  if strategy == ISOLATE:   return t_iso

Function escalate_one_level(strategy):
  if strategy == NORMAL:    return SPECULATE
  if strategy == SPECULATE: return SHED
  if strategy == SHED:      return ISOLATE
  if strategy == ISOLATE:   return ISOLATE  // cannot escalate further

Function de_escalate_one_level(strategy):
  if strategy == ISOLATE:   return SHED
  if strategy == SHED:      return SPECULATE
  if strategy == SPECULATE: return NORMAL
  if strategy == NORMAL:    return NORMAL
```

### 3.4 State Transition Diagram

```
                     sev >= t_iso
            +---------------------------+
            |                           v
  +--------+--------+     +---------+--------+     +----------+-------+
  |                  |     |                  |     |                  |
  |    SPECULATE     +---->+     SHED         +---->+    ISOLATE       |
  |  (hedge to       |     |  (reduce weight, |     |  (remove from    |
  |   healthy node)  |     |   AIMD control)  |     |   pool, probe)   |
  +--------+---------+     +---------+--------+     +--------+---------+
     ^     |                   ^     |                        |
     |     | sustained         |     | sustained              |
     |     | sev < t_spec      |     | sev < t_shed           |
     |     | - HYSTERESIS      |     | - HYSTERESIS           |
     |     v                   |     v                        |
  +--+-----+--------+         |  (de-escalate                |
  |                  |         |   one level)                 |
  |     NORMAL       +---------+                              |
  |                  |  sev >= t_shed                          |
  +------------------+                                        |
     ^                                                        |
     |           Recovery probe: severity < theta_rec         |
     +--------------------------------------------------------+
                    (reintegrate at w_min, enter SHED)
```

**Transition rules summary**:
- **Escalation** (upward): Immediate when severity crosses adaptive threshold
- **De-escalation** (downward): Requires severity to drop below threshold minus hysteresis band, sustained for DEBOUNCE consecutive monitoring intervals
- **Emergency escalation**: When `slo_dist < 0`, each slow node is escalated one level beyond what severity alone would dictate
- **Recovery from ISOLATE**: Only via probe cycle; transitions to SHED first (never directly to NORMAL)

### 3.5 AIMD Weight Controller (for SHED strategy)

```
Algorithm: AIMDWeightController

State per node:
  weight[i]          -- current routing weight (initialized to C_i / sum(C))
  stable_count[i]    -- consecutive intervals without degradation

Constants:
  ALPHA = 0.05       -- additive increase per stable interval
  BETA  = 0.5        -- multiplicative decrease factor
  W_MIN = 0.05       -- minimum weight before isolation trigger
  STABLE_THRESHOLD = 3  -- stable intervals before increasing weight

Procedure UpdateWeights():
  for each node i where strategy[i] == SHED:
    if severity[i] is increasing OR slo_dist is decreasing:
      weight[i] = max(weight[i] * BETA, W_MIN)
      stable_count[i] = 0
      if weight[i] == W_MIN:
        // Node too slow to be useful; recommend isolation
        recommend_escalation(i, ISOLATE)
    else:
      stable_count[i] += 1
      if stable_count[i] >= STABLE_THRESHOLD:
        weight[i] = min(weight[i] + ALPHA, weight_baseline[i])

  // Redistribute: healthy nodes absorb shed load proportionally
  total_shed = sum(weight_baseline[i] - weight[i]) for all shedding nodes
  for each node j where strategy[j] == NORMAL:
    weight[j] = weight_baseline[j] + total_shed * (C_j / sum(healthy C))

  Normalize all weights to sum to 1.0
```

### 3.6 Multi-Node Fault Handling

When multiple nodes experience simultaneous slow faults (e.g., correlated thermal events in the same rack):

```
Procedure HandleMultiNodeFaults():
  slow_nodes = {i : severity[i] > t_spec}
  total_slow_capacity = sum(C_i for i in slow_nodes)
  healthy_capacity = sum(C_j for j not in slow_nodes)

  if healthy_capacity < lambda:
    // Cannot absorb all traffic even with full isolation
    // Mixed strategy: shed load on all slow nodes proportionally
    // Accept partial SLO violation as unavoidable
    for each node i in slow_nodes:
      weight[i] = (1 / severity[i]) * C_i  // inversely proportional to severity
    Normalize weights

  elif healthy_capacity < lambda * (1 + SPARE_MIN):
    // Can absorb but no spare for speculation
    // Force all slow nodes into SHED, skip SPECULATE
    for each node i in slow_nodes:
      strategy[i] = SHED

  else:
    // Sufficient capacity; apply normal per-node decision logic
    // (Algorithm from Section 3.3)
```

### 3.7 Danger Zone Awareness

ADR's key finding is that danger zones are narrow and workload-dependent. We incorporate this insight in three ways:

**Preemptive escalation**: Monitor the rate of change of fault severity. If severity is increasing rapidly and the system is near the danger zone, escalate before crossing the cliff:
```
if d(severity)/dt > danger_rate_threshold AND slo_dist < D_preemptive:
    escalate_one_level()  // Analogous to TCP congestion avoidance
```

**Workload-dependent thresholds**: Maintain workload-specific threshold profiles (learned offline or via ADR-style online characterization):
```
thresholds = load_profile(current_workload_type)
// e.g., read-heavy workloads have wider danger zones -> more lenient thresholds
// write-heavy workloads have narrower danger zones -> tighter thresholds
```

**Hysteresis to prevent oscillation**: Near danger zone boundaries, small fluctuations cause rapid strategy switching. The HYSTERESIS constant (Section 3.3) and DEBOUNCE counter prevent this.

---

## 4. System Architecture

### 4.1 Architecture Diagram

```
+------------------------------------------------------------------+
|                        Control Plane                              |
|                                                                   |
|  +------------+     +------------+     +-----------+              |
|  |            |     |            |     |           |              |
|  |  Monitor   +---->+ Detector   +---->+ Strategy  |              |
|  |            |     |            |     | Selector  |              |
|  +-----+------+     +------------+     +-----+-----+              |
|        |              (ADR-style            |                     |
|        |               adaptive             |                     |
|        |               detection)           |                     |
|        | metrics                            | strategy_map        |
|        | (per node,                         | weight_map          |
|        |  per interval)                     |                     |
|  +-----+------+                       +-----v-----+              |
|  |            |                       |           |              |
|  | Metrics    |                       | Executor  |              |
|  | Store      |                       |           |              |
|  | (sliding   |                       +-----+-----+              |
|  |  window)   |                             |                    |
|  +------------+                             |                    |
+------------------------------------------------------------------+
                                              |
              +-------------------------------+--------------------+
              |                               |                    |
              v                               v                    v
  +-----------+---+             +-------------+-+    +------------+-+
  |               |             |               |    |              |
  | Load Balancer |             | Speculation   |    | Recovery     |
  | (weighted     |             | Manager       |    | Prober       |
  |  routing)     |             | (hedge/cancel)|    | (isolated    |
  |               |             |               |    |  nodes)      |
  +-------+-------+             +-------+-------+    +------+-------+
          |                             |                    |
          v                             v                    v
  +-------+-------+-------+-------+-------+-------+-------+-------+
  |       |       |       |       |       |       |       |       |
  | w_1   | w_2   | w_3   | w_4   | w_5   | w_6   | w_7   | w_8   |
  |NORMAL |NORMAL |SPEC   |SHED   |SHED   |ISOLATE|NORMAL |NORMAL |
  +-------+-------+-------+-------+-------+-------+-------+-------+
                      Data Plane (Worker Nodes)
```

### 4.2 Component Descriptions

**Monitor** (runs every `tau = 500ms`):
- Collects per-node metrics: request latency (P50, P95, P99), throughput, queue depth
- Computes system-level aggregates: overall P99 latency, total throughput, spare capacity
- Stores metrics in a sliding window buffer (window size adaptive to workload frequency, per ADR: `window_length = 10 * current_frequency`)

**Detector** (triggered by Monitor):
- Implements ADR-style adaptive detection per node
- Computes `severity_i(t)` using peer comparison: `severity_i = 1 - (median_peer_latency / node_i_latency)`
- Cross-validates with frequency state checker to filter transient spikes vs. genuine slow faults (ADR's continuous slowdown checker + workload change checker)
- Detection speed: 0.9--1.3 seconds on average (per ADR empirical results)
- Outputs: per-node severity scores, danger zone proximity estimate

**Strategy Selector** (triggered by Detector output):
- Runs the `AdaptiveStrategySelector` algorithm (Section 3.3)
- Inputs: severity scores, SLO distance, spare capacity, current strategy map
- Outputs: updated strategy map, updated weight map
- Logs all transitions for post-hoc analysis and debugging

**Executor** (applies decisions):
- **Load Balancer**: Updates routing weights based on weight map. Uses weighted round-robin or weighted power-of-two-choices (Mitzenmacher 2001).
- **Speculation Manager**: For nodes in SPECULATE state, intercepts requests and dispatches hedged copies. Manages cancellation on first response via cross-server signaling (tied requests, per Dean and Barroso).
- **Recovery Prober**: Periodically sends test requests to isolated nodes. Reports results back to Detector for reintegration decisions.

### 4.3 Data Flow

```
1. Worker nodes report latency/throughput metrics to Monitor
   (push-based, piggyback on response metadata, or pull every tau)

2. Monitor -> Metrics Store: raw metrics + sliding window statistics
   Monitor -> Detector: aggregated per-node statistics

3. Detector -> Strategy Selector:
   - severity_i(t) per node
   - system-level slo_dist(t)
   - spare capacity spare(t)

4. Strategy Selector -> Executor:
   - strategy_map: per-node strategy assignment
   - weight_map: per-node routing weights (for SHED nodes)

5. Executor -> Load Balancer: update routing weights
   Executor -> Speculation Manager: enable/disable hedging per node
   Executor -> Recovery Prober: add/remove nodes from probe list

6. Recovery Prober -> Detector: probe results for isolated nodes
   (feeds back into severity computation for reintegration decisions)
```

### 4.4 Timing and Overhead

| Component | Execution frequency | Expected overhead |
|-----------|-------------------|-------------------|
| Monitor | Every 500ms | < 1ms (metric aggregation) |
| Detector | Every 500ms | < 5ms (statistical computation over sliding window) |
| Strategy Selector | Every 500ms | < 1ms (threshold comparisons + state machine) |
| Weight update (AIMD) | Every 1s | < 1ms (arithmetic) |
| Recovery probe | Every 30s per isolated node | 5 probe requests per node |

Total control plane overhead: < 10ms per cycle, negligible relative to typical inference latency (20--200ms).

---

## 5. Evaluation Plan

### 5.1 Simulation Setup

**Simulator**: Custom discrete-event simulator. No existing simulator natively supports parametric slow-fault modeling with configurable severity distributions (see slow-fault-modeling.md Section 2.4). The simulator should model:
- Request arrival (Poisson process)
- Per-node queuing (M/D/1 for deterministic inference, M/G/1 for variable inference)
- Slowdown factor application on processing time
- Load balancer with dynamic weight updates
- Hedging with cancellation

**System configuration**:
| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Cluster size | N = 16 worker nodes (baseline), scalable to 64 | Typical inference cluster |
| Per-node capacity | C = 100 req/s | Normalized for simplicity |
| Total system capacity | 1,600 req/s | N * C |
| Request arrival | Poisson process at varying lambda | 50%--95% of total capacity |
| Per-request latency (healthy) | T_base = 20ms | Typical DNN inference |
| SLO target | P99 latency <= 100ms (5x base) | Standard inference SLO |
| Decision epoch | tau = 500ms | Balances responsiveness vs. stability |
| AIMD alpha | 0.05 (5% of max weight per epoch) | Conservative reintroduction |
| AIMD beta | 0.5 (halve weight on degradation) | Standard multiplicative decrease |

**Fault injection** (per Section 1.2 fault model):
- Slowdown factor `s` drawn from configurable distributions:
  - **Mild**: `s ~ Uniform(1.2, 1.5)` -- severity 0.17--0.33
  - **Moderate**: `s ~ Uniform(1.5, 3.0)` -- severity 0.33--0.67
  - **Severe**: `s ~ Uniform(3.0, 10.0)` -- severity 0.67--0.90
  - **Progressive**: `s(t) = 1.0 + 0.1 * (t - t_onset)` -- thermal throttling
- Fault onset: exponential inter-arrival with mean 60s
- Fault duration: log-normal (mean 30s, std 20s), or permanent
- Simultaneous faulty nodes: 1 (default), up to N/4 for multi-fault scenarios

### 5.2 Baselines

| Baseline | Description | What it measures |
|----------|-------------|-----------------|
| **No mitigation** | Continue routing as normal; no response to slow faults | Lower bound: how bad things get without intervention |
| **Fixed speculation** | Always hedge requests to slow nodes (when severity > 0.1); no shedding or isolation | Cost/benefit of speculation-only (straggler literature approach) |
| **Fixed shedding** | Always redistribute load from slow nodes using static 50% weight reduction | Cost/benefit of shedding-only |
| **Fixed isolation** | Always isolate nodes above a fixed severity threshold (> 0.3); IASO-style binary response | Cost of aggressive isolation (capacity loss) |
| **Oracle** | Offline-optimal strategy selection with perfect knowledge of fault duration, severity trajectory, and system state | Upper bound on achievable performance |
| **ADR + default** | ADR detection with the system's default single mitigation mechanism | State-of-the-art comparison point |

### 5.3 Metrics

**Primary metrics**:
| Metric | Definition | Optimization target |
|--------|-----------|---------------------|
| Throughput | Requests successfully completed per second | Maximize |
| P50 latency | Median request latency | Report |
| P95 latency | 95th percentile request latency | Report |
| P99 latency | 99th percentile request latency | <= L_target |
| SLO violation rate | Fraction of requests exceeding L_target | Minimize |
| Goodput | Requests meeting SLO / total requests (per DistServe) | Maximize |

**Secondary metrics**:
| Metric | Definition | Purpose |
|--------|-----------|---------|
| Resource overhead | Extra compute (speculation copies + probes) / total compute | Mitigation cost |
| Strategy transition count | Number of strategy changes per unit time | Stability indicator |
| Time-to-mitigate | Time from fault onset to first strategy activation | Responsiveness |
| Capacity utilization | Fraction of total system capacity effectively used | Efficiency |
| Recovery accuracy | Fraction of reintegrated nodes that remain stable for > 30s | Recovery quality |

### 5.4 Workload Scenarios

**Scenario 1: Single node, varying severity**
- One node degrades across the full severity spectrum: s in {1.1, 1.2, 1.5, 2.0, 3.0, 5.0, 10.0}
- System at 70% load
- Goal: demonstrate that the adaptive framework selects the right strategy at each severity level, outperforming any single fixed strategy across all severities

**Scenario 2: Progressive degradation (thermal throttling)**
- One node's severity increases linearly over time: `s(t) = 1.0 + 0.05 * t`
- Goal: demonstrate smooth strategy escalation (NORMAL -> SPECULATE -> SHED -> ISOLATE) as severity increases, with timely transitions that avoid the danger zone cliff

**Scenario 3: Flash crowd under slow fault**
- One node at moderate severity (s = 2.0)
- Request rate spikes from 70% to 95% of capacity
- Goal: demonstrate that reduced spare capacity triggers strategy transition from SPECULATE to SHED automatically

**Scenario 4: Multi-node correlated failure**
- 4 of 16 nodes develop slow faults simultaneously (rack-level thermal event)
- Severity: moderate (s ~ Uniform(1.5, 3.0))
- Goal: demonstrate multi-node fault handling (Section 3.6) where full isolation is not viable due to capacity constraints

**Scenario 5: Fluctuating fault**
- One node alternates between normal and degraded (duty cycle: 10s normal / 5s slow at s = 3.0)
- Goal: test hysteresis and debounce mechanisms; verify the framework avoids rapid oscillation between strategies

**Scenario 6: Cascading degradation**
- One node fails slowly; its redistributed load causes a second node to overheat and degrade
- Goal: test whether the framework handles emergent multi-node faults triggered by its own mitigation actions

**Scenario 7: Recovery dynamics**
- One node degrades severely (s = 5.0), is isolated, then recovers after 60s
- Goal: measure recovery probe accuracy and AIMD reintegration speed; verify that reintegration is gradual and stable

### 5.5 Statistical Requirements

- Each scenario: 30 independent runs with different random seeds
- Report mean and 95% confidence intervals for all metrics
- Warmup period: 30s (discard) before measurement
- Measurement period: 300s per run
- Sensitivity analysis on key parameters: `THETA_SPEC`, `THETA_SHED`, `THETA_ISO`, `tau`, `ALPHA`, `BETA`

---

## 6. Research Contributions Summary

### 6.1 Novel Contributions

1. **Multi-strategy selection framework for slow fault mitigation**: The first system to define a strategy space of {speculative execution, load shedding, isolation} and provide a concrete algorithm for dynamically selecting among them based on runtime signals. All prior work uses a single fixed strategy (IASO: reboot/shutdown; MapReduce literature: speculative execution only; cloud practice: instance replacement).

2. **SLO-distance-driven adaptive thresholds for strategy transitions**: Unlike ADR which uses adaptive thresholds only for detection, we use the SLO distance as a control signal that dynamically adjusts the severity thresholds for strategy transitions. This ensures that strategy aggressiveness scales with how close the system is to violating its SLO.

3. **Danger-zone-aware escalation**: We operationalize ADR's danger zone finding by designing the strategy selector to be more aggressive near danger zone boundaries -- tightening thresholds when urgency is high, and supporting preemptive escalation based on severity rate-of-change. ADR identifies the danger zone but does not use it for mitigation decisions.

4. **AIMD-based recovery and weight management**: We adapt TCP congestion control's AIMD principle for load shedding weight management and node recovery, providing a principled mechanism for gradual reintegration that prevents oscillation. While AIMD has been used for load shedding in messaging systems (Zalando 2024), its application to slow fault recovery in inference serving is novel.

5. **Formal slow fault severity model for simulation**: We provide a parametric fault model (multiplicative slowdown factor with four temporal patterns from Gunawi et al.) suitable for systematic simulation studies. Existing fault injection tools lack graduated severity models.

### 6.2 Building on Existing Work

| Component | Builds on | Our extension |
|-----------|-----------|---------------|
| Detection mechanism | ADR (NSDI 2025) | Use ADR as detection front-end; add strategy selection layer |
| Danger zone concept | ADR (NSDI 2025) | Exploit for preemptive escalation and adaptive thresholds |
| Fault taxonomy | Fail-Slow at Scale (FAST 2018) | Formalize 4 temporal patterns as simulation parameters |
| Severity quantification | Perseus (FAST 2023) | Adapt slowdown ratio as continuous severity signal |
| Hedged requests | Dean & Barroso (CACM 2013) | Integrate as one strategy in multi-strategy framework |
| AIMD control | TCP congestion control; Zalando (2024) | Apply to inference load shedding and node recovery |
| SLO-aware scheduling | Clockwork (OSDI 2020), SLAI (2025) | Extend to incorporate degraded-node handling |
| Thermal modeling | TAPAS (ASPLOS 2025) | Use progressive degradation model for fault simulation |
| Coded computation | CoCoI (WiOpt 2025) | Alternative speculation mechanism in strategy space |
| Graceful degradation | DAGOR (SoCC 2018) | Priority-based shedding model for inference |

### 6.3 Positioning Relative to Key Prior Work

**vs. IASO (ATC 2019)**: IASO detects slow faults and responds with reboot/shutdown -- a binary, coarse-grained response. Our framework introduces graduated responses that preserve node capacity when possible, only escalating to isolation when necessary. We also add SLO-awareness and AIMD-based recovery, neither of which IASO supports.

**vs. ADR (NSDI 2025)**: ADR provides excellent adaptive detection but explicitly delegates mitigation to existing system mechanisms. Our work fills exactly this mitigation gap with a principled strategy selection framework that leverages ADR's detection and danger zone insights as inputs.

**vs. Straggler mitigation (LATE, Mantri, Dolly)**: These systems use fixed speculative execution strategies for batch processing with minute-scale latency tolerance. Our framework targets millisecond-scale inference serving with SLO constraints, and dynamically selects among multiple strategies rather than relying on speculation alone.

**vs. Inference serving systems (Clockwork, vLLM, DistServe)**: These systems optimize for normal operation (deterministic scheduling, memory management, prefill-decode disaggregation) but lack mechanisms for handling degraded nodes. Our framework is complementary -- it adds a slow fault mitigation layer on top of existing serving systems.

**vs. FALCON (2024)**: FALCON provides multi-level straggler mitigation for distributed training. Our work addresses inference serving, where per-request SLO constraints fundamentally change the problem: training tolerates batch-level delays, but inference cannot tolerate individual request latency violations.

**vs. TAPAS (ASPLOS 2025)**: TAPAS prevents slow faults proactively through thermal-aware placement and scheduling. Our framework is complementary -- we handle the reactive case where slow faults occur despite preventive measures, choosing the right mitigation strategy dynamically.

---

## References

1. Gunawi et al., "Fail-Slow at Scale: Evidence of Hardware Performance Faults in Large Production Systems," USENIX FAST 2018.
2. Panda et al., "IASO: A Fail-Slow Detection and Mitigation Framework for Distributed Storage Services," USENIX ATC 2019.
3. Lu et al., "Perseus: A Fail-Slow Detection Framework for Cloud Storage Systems," USENIX FAST 2023.
4. Lu et al., "One-Size-Fits-None: Understanding and Enhancing Slow-Fault Tolerance in Modern Distributed Systems," USENIX NSDI 2025.
5. Dean and Barroso, "The Tail at Scale," Communications of the ACM, 2013.
6. Zaharia et al., "LATE: Longest Approximate Time to End," OSDI 2008.
7. Ananthanarayanan et al., "Mantri: Reining in Stragglers in MapReduce," OSDI 2010.
8. Ananthanarayanan et al., "Dolly: Full Task Cloning for Small Jobs," NSDI 2013.
9. Crankshaw et al., "Clipper: A Low-Latency Online Prediction Serving System," NSDI 2017.
10. Gujarati et al., "Serving DNNs like Clockwork: Performance Predictability from the Bottom Up," OSDI 2020.
11. Qiu et al., "TAPAS: Thermal- and Power-Aware Scheduling for LLM Inference in Cloud Platforms," ASPLOS 2025.
12. Huang et al., "CoCoI: Distributed Coded Inference System for Straggler Mitigation," WiOpt 2025.
13. Zhou et al., "Overload Control for Scaling WeChat Microservices (DAGOR)," SoCC 2018.
14. Zalando Engineering, "Enhancing Distributed System Load Shedding with TCP Congestion Control Algorithm," 2024.
15. Kwon et al., "Efficient Memory Management for Large Language Model Serving with PagedAttention (vLLM)," SOSP 2023.
16. Zhong et al., "DistServe: Disaggregating Prefill and Decoding for Goodput-optimized Large Language Model Serving," OSDI 2024.
17. FALCON, "Straggler Detection and Mitigation for Large-Scale Hybrid-Parallel Training," 2024.
18. Lee et al., "Shard Manager: A Generic Shard Management Framework for Geo-distributed Applications," SOSP 2021.
19. Eriksen et al., "Global Capacity Management With Flux," OSDI 2023.
20. Rzadca et al., "Autopilot: Workload Autoscaling at Google," EuroSys 2020.
21. Mitzenmacher, "The Power of Two Choices in Randomized Load Balancing," IEEE TPDS, 2001.
