# Survey: ADR Danger Zone and SLO-Aware Scheduling

## 1. ADR (NSDI 2025): One-Size-Fits-None

### 1.1 Paper Overview

**Title**: "One-Size-Fits-None: Understanding and Enhancing Slow-Fault Tolerance in Modern Distributed Systems"
**Authors**: Ruiming Lu, Yunchi Lu, Yuxuan Jiang, Guangtao Xue (SJTU), Peng Huang (UMich)
**Venue**: NSDI 2025 (22nd USENIX Symposium on Networked Systems Design and Implementation)

The paper presents the first comprehensive study of how distributed systems tolerate slow faults (fail-slow behavior), along with a testing pipeline (Xinda) and an adaptive detection library (ADR).

### 1.2 The Danger Zone Concept

**Definition**: A narrow range of fault severity where a slight increase causes disproportionately large performance degradation. The degradation escalates dramatically from a moderate ~10% to an unbearable ~50% within this zone.

**Key property**: The danger zone is narrow, making early alerting extremely challenging. By the time a static threshold catches the degradation, the system may already be deep in catastrophic territory.

**System-specific danger zones (network delay injection)**:

| System     | Workload    | Danger Zone Range |
|-----------|-------------|-------------------|
| Cassandra | Read-only   | 0.2 ms -- 3 ms   |
| Cassandra | Mixed       | 0.1 ms -- 2 ms   |
| Cassandra | Write-only  | 0.1 ms -- 1 ms   |
| etcd      | Read-only   | 1 ms -- 2 ms     |
| etcd      | Write-dominant | Not obvious (Raft alleviates) |
| HBase     | All workloads | Present, low variance (1.1x diff across workloads) |
| HDFS      | -           | No clear danger zone |
| Kafka     | Batch mode  | Not obvious (batching alleviates) |

**Critical insight for our work**: The danger zone is workload-dependent and system-specific. A 1 ms network slow fault can cause 25% degradation in some systems, while others need 100 ms to show similar impact. This strongly supports the need for adaptive, per-context mitigation rather than one-size-fits-all strategies.

### 1.3 ADR: Adaptive Detection at Runtime

ADR is a lightweight library that replaces static thresholds with dynamic, runtime-adaptive detection.

**Core algorithm**:
1. **Sliding window monitoring**: Tracks response values (latency, throughput) over a sliding window whose length is positively correlated with the current operation frequency: `window_length = 10 * current_frequency`. This makes the window adaptive to workload changes.

2. **99th percentile threshold**: Instead of a fixed threshold, ADR computes the P99 of recent observations as the adaptive threshold. A value falling below this percentile is flagged as potentially anomalous.

3. **Cross-validation with frequency states**: ADR uses two state checkers:
   - **Continuous slowdown checker**: Verifies that the observed slowdown is persistent, not transient.
   - **Workload change checker**: Distinguishes genuine slow faults from natural workload fluctuations. If frequency is continuously decreasing (not due to workload drop), it confirms a slow fault.

4. **Detection speed**: Slow faults are detected in 0.9--1.3 seconds on average.

**Results**: ADR reduces performance degradation by 65% on average compared to static thresholds, with low overhead.

### 1.4 ADR Limitations (Explicitly Acknowledged)

1. **Cannot detect during system startup**: ADR needs baseline observations to establish adaptive thresholds; no history is available at boot time.
2. **Requires developer annotation**: Developers must manually mark which variables to monitor. ADR cannot automatically discover the right metrics.
3. **Detection only, not mitigation**: ADR focuses on detecting slow faults more accurately. It relies on the system's existing mitigation mechanisms (e.g., Cassandra's dynamic snitch, etcd's leader transfer). It does not propose new mitigation strategies.
4. **No strategy selection**: ADR does not address which mitigation action to take or how to choose among alternatives based on severity.
5. **Per-node detection**: Does not consider system-wide coordination or collective decision-making.

### 1.5 Relevance to Our Adaptive Strategy Selection

ADR fills the detection gap but explicitly leaves the mitigation gap open. Key takeaways:
- The danger zone concept validates that fault severity is not linear with impact -- there are phase transitions that demand different responses.
- The narrow danger zones (sub-millisecond to a few milliseconds) mean the decision to switch strategies must be fast.
- ADR's adaptive threshold mechanism could serve as our detection front-end, but we need to build the strategy selection layer on top.
- The workload-dependence of danger zones means our strategy selector must also be workload-aware.

---

## 2. SLO-Aware Scheduling Systems

### 2.1 Shard Manager (SOSP 2021)

**Authors**: Meta/Facebook
**Venue**: ACM SOSP 2021

**Overview**: A generic shard management framework for geo-distributed applications at Meta, managing shard placement, failover, and load balancing across millions of servers.

**Key mechanisms**:
- Simultaneously balances multiple resources (compute, memory, storage) with user-configurable priorities.
- Periodically collects per-replica load and per-server capacity for load balancing decisions.
- Handles planned events (software upgrades, ~1000x more frequent than failures) without violating availability.

**Signals used**: Per-replica load metrics, per-server capacity, geographic constraints.

**Relevance**: Demonstrates that production systems need multi-dimensional balancing. Our strategy selector similarly must consider multiple signals (fault severity, remaining capacity, SLO distance) simultaneously.

### 2.2 Flux: Global Capacity Management (OSDI 2023)

**Authors**: Meta
**Venue**: USENIX OSDI 2023

**Overview**: Automates capacity regionalization for thousands of services spanning millions of servers. Replaces manual, bottoms-up capacity negotiation with top-down, automated optimization.

**Key mechanisms**:
- Uses RPC tracing to build service capacity models automatically.
- Computes optimal joint capacity + traffic distribution plans across tens of regions.
- Orchestrates safe rebalancing of capacity and traffic continuously.

**Relevance**: Flux demonstrates that system-wide optimization requires understanding service dependencies and global state. For our work, this reinforces that strategy selection cannot be purely local -- it should consider the global system capacity picture.

### 2.3 SLO-Aware LLM Inference Scheduling

Several recent systems address SLO-aware scheduling for LLM inference:

**SLAI (SLO-Aware LLM Inference)**: Prioritizes decode iterations for requests close to missing per-token deadlines. Reorders prefill requests by prompt length. Uses real-time memory and queue observations.

**SLO-Aware Scheduler (arXiv 2025)**: A decoupled scheduler with four components:
1. **Request profiler**: Characterizes incoming requests
2. **Latency predictor**: Combines request info with output distribution and memory usage to predict per-request latency
3. **Priority mapper**: Uses SLO + predicted latency to determine priority order
4. **Instance queues**: Dispatches prioritized requests to execution instances

**Key insight**: These systems focus on request-level scheduling to meet SLOs but assume healthy nodes. They do not address what happens when nodes degrade (slow fault) -- they lack a mitigation dimension.

### 2.4 TAPAS: Thermal- and Power-Aware Scheduling (ASPLOS 2025)

**Authors**: Microsoft Research
**Venue**: ASPLOS 2025

**Overview**: First thermal- and power-aware scheduling scheme for LLM inference clusters. Addresses GPU thermal throttling -- a direct cause of slow faults in inference.

**Key mechanisms**:
1. **Thermal-aware VM placement**: Places GPU VMs considering historical temperature, power, and load data.
2. **Load-aware request routing**: Routes requests based on per-VM load, temperature, and power slack.
3. **Hierarchical reconfiguration**: Reconfigures instances when temperature/power exceeds safe limits.

**Results**:
- Reduces maximum temperature by 17%, peak row power by 23%
- Reduces thermal and power throttling events by 97% and 99% respectively
- Maintains P99 tail latency while enabling 40% additional capacity through oversubscription

**Relevance**: TAPAS is highly relevant because GPU thermal throttling is a primary cause of slow faults in inference. TAPAS prevents slow faults proactively through placement. Our work is complementary -- we handle the case where slow faults occur despite preventive measures, choosing the right mitigation strategy dynamically.

---

## 3. Control Theory for SLO Management

### 3.1 PID Controllers in Distributed Systems

**Core idea**: Use Proportional-Integral-Derivative controllers to maintain system metrics (latency, throughput, utilization) at target values by adjusting resources.

**Key advantage**: PID controllers do not need a precise analytical model of the controlled system. They use the error signal (difference between target SLO and observed metric) directly.

**Challenges in distributed settings**:
- Most inter-relationships in computing systems are nonlinear, making classical linear control theory insufficient.
- Bimodal behavior: systems behave fundamentally differently when overloaded (utilization = 100%) vs. underloaded (utilization inversely proportional to allocation).
- Nonlinear control theory and adaptive control are much harder to understand and apply in practice.

**Practical applications**:
- **Autopilot (Google, EuroSys 2020)**: Uses ML-based recommenders with control-theoretic feedback to autoscale Borg workloads. Reduces resource slack from 46% (manual) to 23% (automated). Reduces OOM-impacted jobs by 10x. Handles 48%+ of Google's fleet-wide resource usage.
- **ARIMA-PID**: Combines time-series prediction (ARIMA) with PID control for container autoscaling. Uses prediction to be proactive rather than purely reactive.
- **DeepScaling (SoCC 2022)**: Microservice autoscaling for stable CPU utilization using deep learning + control theory.

**Feedback loop parameters**: Typical control loops operate at 30-second intervals, balancing responsiveness with stability.

### 3.2 AIMD (Additive Increase Multiplicative Decrease)

**Origin**: TCP congestion control. Conservative increase (additive) during stable periods; aggressive decrease (multiplicative) at first sign of trouble.

**Application to load shedding (Zalando, 2024)**:
- Applied AIMD to manage event ingestion rate into distributed messaging systems.
- **Priority-based rate adjustment**:
  - Speed-up phase: High-priority events get larger additive increases (P1: +15/sec vs P3: +5/sec)
  - Slow-down phase: High-priority events face smaller multiplicative decreases (P1: -20% vs P3: -60%)
- Three components: Statistics Collector, Congestion Detector, Throttle (per event listener)
- Production results over 6 months showed significant queue backlog reduction while maintaining critical request processing.

**Relevance to our work**: AIMD provides a natural model for our load shedding strategy. When a slow node is detected, we can multiplicatively decrease its load share, then additively increase it if the node recovers. The priority-based variant is especially relevant -- we can shed low-priority inference requests first.

### 3.3 Control-Theoretic SLO Management Pattern

A common pattern emerges across these systems:

```
error = target_SLO - observed_metric
adjustment = Kp * error + Ki * integral(error) + Kd * derivative(error)
resource_allocation = current_allocation + adjustment
```

For our adaptive strategy selection, the "SLO distance" (how far current latency is from the SLO target) serves as the error signal. The strategy selection can be viewed as a controller where:
- **Small error** (near SLO but not violating): Speculative execution (mild intervention)
- **Medium error** (approaching danger): Load shedding (moderate intervention)
- **Large error** (SLO violated or imminent): Isolation (aggressive intervention)

---

## 4. Overload Control and Graceful Degradation

### 4.1 DAGOR: WeChat Microservice Overload Control (SoCC 2018)

**Authors**: Tencent (WeChat)
**Venue**: ACM SoCC 2018

**Overview**: Service-agnostic, system-centric overload control for WeChat's microservice architecture. Deployed in production for 5+ years.

**Key mechanisms**:
- **Overload detection**: Uses average queuing time of requests as the primary signal. Simple but effective.
- **Collaborative load shedding**: Each microservice monitors its own load and triggers shedding collaboratively with related services.
- **Priority-based admission**: Each request receives a business priority + user priority. All subsequent microservice calls inherit the same priority, ensuring consistent admission/rejection.

**Relevance**: DAGOR's priority-based, collaborative shedding model maps well to our distributed inference scenario. When a GPU node slows down, we can shed requests based on priority while maintaining consistency across the inference pipeline.

### 4.2 Graceful Degradation Strategies

**General principles** for progressive degradation in distributed systems:

1. **Health monitoring + early detection**: Continuously monitor component health to detect issues before they impact users. This maps to ADR's adaptive detection.

2. **Circuit breaker pattern**: Monitor failing calls to a downstream node. If failures exceed a threshold, stop sending requests (open circuit). Periodically probe to test recovery (half-open). Resume if recovered (close circuit). This maps to our isolation strategy with recovery.

3. **Feature flags and kill switches**: Runtime controls that can disable non-critical features progressively. Analogous to our load shedding -- progressively reduce workload on degraded nodes.

4. **Traffic shaping**: Prioritize critical requests during degradation. Delay or drop less important ones.

**Industry data**: Studies indicate 28% of outages could have been mitigated or avoided through graceful degradation techniques.

### 4.3 Progressive Degradation Model

A general progression observed across systems:

| Stage | Detection Signal | Response | Cost |
|-------|-----------------|----------|------|
| 1. Normal | Metrics within bounds | No action | None |
| 2. Warning | Approaching danger zone | Speculative execution / hedging | Extra compute |
| 3. Degraded | In danger zone | Load shedding / rebalancing | Underutilized node |
| 4. Critical | Past danger zone | Isolation + failover | Lost capacity |
| 5. Recovery | Metrics improving | Gradual reintroduction (AIMD-style) | Probe overhead |

This maps directly to our three-strategy framework:
- Stage 2 -> Speculative execution
- Stage 3 -> Load shedding
- Stage 4 -> Isolation
- Stage 5 -> AIMD-style recovery (additive increase of load back to the recovered node)

---

## 5. Straggler Mitigation Techniques

### 5.1 Speculative Execution Variants

**Classic speculative execution** (MapReduce-style): Wait, observe relative progress rates, launch copies of predicted stragglers. Simple but reactive and resource-expensive.

**Hedged requests** (Google, "The Tail at Scale"): Send redundant requests proactively to multiple replicas. Cancel extras when the first response arrives. Effective for latency-sensitive services with spare capacity.

**Coded computation** (CoCoI, WiOpt 2025): Split inference tasks and apply error-correcting codes so that any k-of-n results suffice. Tolerates stragglers algebraically rather than through brute-force duplication. Especially effective when communication cost >> computation cost.

**Proactive prediction** (LASER, DPro-SM): Use deep learning (LSTM) to predict stragglers before they manifest. Enables preemptive mitigation rather than reactive copying.

### 5.2 Gap in Straggler Mitigation Literature

Almost all straggler mitigation work assumes a single strategy (typically speculative execution). No existing work addresses:
- When to switch from speculative execution to load shedding to isolation
- How to combine strategies based on fault severity and system state
- How to incorporate SLO distance into the strategy decision

This is precisely our research gap.

---

## 6. Synthesis: Implications for Adaptive Strategy Selection

### 6.1 Key Insights Across All Reviewed Work

1. **Detection is largely solved; mitigation strategy selection is not.** ADR provides adaptive detection. TAPAS prevents some faults proactively. But no system dynamically selects among multiple mitigation strategies.

2. **The danger zone demands fast decisions.** With danger zones as narrow as 0.1--3 ms of added latency, the strategy selector must operate at sub-second timescales.

3. **SLO distance is the natural control signal.** Control theory approaches (PID, AIMD) all center on the error between target and observed metrics. Our "SLO distance" (remaining margin before violation) naturally serves this role.

4. **AIMD provides a recovery model.** After isolating or shedding load from a slow node, AIMD-style gradual reintroduction prevents oscillation while testing recovery.

5. **Priority-based shedding is production-proven.** DAGOR (WeChat) and Zalando both demonstrate that priority-aware load shedding works at scale.

6. **Workload-awareness is essential.** ADR shows danger zones are workload-dependent. Strategy selection must incorporate workload characteristics.

### 6.2 Proposed Decision Framework (Sketch)

```
Inputs:
  - fault_severity: from ADR detection (continuous signal)
  - slo_distance: (SLO_target - current_p99_latency) / SLO_target
  - spare_capacity: available compute across healthy nodes
  - workload_type: read-heavy, write-heavy, mixed, batch

Decision logic:
  if slo_distance > threshold_high AND spare_capacity > min_spare:
      -> speculative_execution  (low severity, enough headroom)
  elif slo_distance > threshold_low:
      -> load_shedding  (moderate severity, redistribute load)
  else:
      -> isolation  (SLO violated or imminent, remove node)

Recovery:
  After any mitigation, monitor recovered node.
  Use AIMD: additively increase load to recovered node.
  If degradation recurs, multiplicatively decrease again.
```

### 6.3 Open Questions

1. **How to set threshold_high and threshold_low?** Static values won't work (ADR's lesson). Need adaptive thresholds for strategy transitions too.
2. **How to handle multi-node slow faults?** If multiple nodes degrade simultaneously, isolation may not be viable (insufficient remaining capacity).
3. **Interaction between strategies**: Can we combine speculative execution with partial load shedding?
4. **Cost modeling**: What is the exact compute cost of speculative execution vs. throughput loss from shedding?
5. **Stability**: How to prevent oscillation between strategies as fault severity fluctuates near thresholds?

---

## References

- Lu et al., "One-Size-Fits-None: Understanding and Enhancing Slow-Fault Tolerance in Modern Distributed Systems," NSDI 2025
- Lee et al., "Shard Manager: A Generic Shard Management Framework for Geo-distributed Applications," SOSP 2021
- Eriksen et al., "Global Capacity Management With Flux," OSDI 2023
- Rzadca et al., "Autopilot: Workload Autoscaling at Google," EuroSys 2020
- Zhou et al., "Overload Control for Scaling WeChat Microservices (DAGOR)," SoCC 2018
- Jovans et al., "TAPAS: Thermal- and Power-Aware Scheduling for LLM Inference in Cloud Platforms," ASPLOS 2025
- Huang et al., "SLO-Aware Scheduling for Large Language Model Inferences," arXiv 2025
- Lin et al., "IASO: A Fail-Slow Detection and Mitigation Framework for Distributed Storage Services," USENIX ATC 2019
- Yang et al., "Perseus: A Fail-Slow Detection Framework for Cloud Storage Systems," USENIX FAST 2023
- Zalando Engineering, "Enhancing Distributed System Load Shedding with TCP Congestion Control Algorithm," 2024
- Dean and Barroso, "The Tail at Scale," Communications of the ACM, 2013
- CoCoI, "Distributed Coded Inference System for Straggler Mitigation," WiOpt 2025
