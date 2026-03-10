# Survey: Straggler Mitigation in Distributed Inference

## 1. Slow Faults (Fail-Slow) in Distributed Systems

### 1.1 Problem Definition

Slow faults (fail-slow failures) refer to situations where a node remains responsive but operates at significantly degraded performance. Unlike crash failures, fail-slow nodes continue responding to heartbeats, preventing traditional fault recovery mechanisms from triggering. Common causes include thermal throttling, memory pressure, network congestion, disk degradation, and firmware bugs.

### 1.2 Key Detection and Mitigation Frameworks

**IASO (USENIX ATC 2019)** [Panda et al.]
- Deployed at Nutanix across 39,000 nodes in production
- Converts software timeout signals into peer-based fail-slow scores
- Detection: compares timeout-derived scores across peer nodes to identify outliers
- Mitigation: binary strategy only -- reboot the slow node; if ineffective, shutdown
- Limitations: intrusive (requires source code modification), node-level granularity only, no graduated response

**Perseus (USENIX FAST 2023)** [Lu et al.]
- Regression-based model for drive-level fail-slow detection in cloud storage
- Detected 304 fail-slow cases across 248K drives over 10 months with high precision
- Non-intrusive: does not require source code modifications
- Limitation: focused exclusively on storage systems; no mitigation framework

**ADR -- Adaptive Detection at Runtime (USENIX NSDI 2025)** [Lu et al.]
- Lightweight adaptive library replacing static thresholds with dynamic ones
- Monitors both value and update frequency of traced variables
- Tested on etcd, HBase, Cassandra, HDFS, CockroachDB
- Key finding: nearly all systems have a "danger zone" where slight increases in fault severity cause dramatic performance degradation
- Reduces performance degradation by 65% on average compared to static thresholds
- Limitations: cannot detect faults during system startup; requires developers to manually annotate monitoring variables; mitigation still relies on existing system mechanisms

### 1.3 The "Tail at Scale" Foundation

**Dean and Barroso (Communications of the ACM, 2013)**
- Foundational work on tail latency in large-scale distributed systems
- Proposed hedged requests: send duplicate request after brief delay (e.g., 95th-percentile latency)
- At Google, hedging after 10ms delay reduced 99.9th-percentile latency from 1,800ms to 74ms with only 2% additional load
- Proposed tied requests: enqueue copies at multiple servers with cross-server cancellation
- Key insight: even rare per-component slowdowns compound into frequent system-level tail latency events

---

## 2. Straggler Mitigation in Batch Processing (MapReduce/Hadoop/Spark)

### 2.1 Speculative Execution Approaches

**Hadoop Native Speculative Execution** [Apache Hadoop]
- Detects tasks running slower than average and launches backup copies
- Simple progress-rate based detection; uses uniform thresholds
- Ineffective in heterogeneous clusters

**LATE Scheduler (OSDI 2008)** [Zaharia et al.]
- Longest Approximate Time to End algorithm
- Estimates remaining execution time rather than using progress rate alone
- Improved Hadoop response times by 2x on 200-node EC2 clusters
- Robust to heterogeneous node performance

**Mantri (OSDI 2010)** [Ananthanarayanan et al.]
- Network-aware task placement with early straggler detection
- Cause-aware straggler handling: different strategies for different root causes
- Decides whether to restart, replicate, or wait based on cost-benefit analysis
- Significant reduction in job latencies at Microsoft

**Dolly (NSDI 2013)** [Ananthanarayanan et al.]
- Full cloning: launches multiple copies of all tasks proactively
- Effective for small interactive jobs; wasteful for large batch jobs

### 2.2 Coded Computation

**Coded Computing (various, 2017--2025)**
- Applies coding theory (inspired by Reed-Solomon codes) to introduce computational redundancy
- Treats stragglers as erasures; recovers results from a subset of completed workers
- Primarily studied for linear operations (matrix multiplication, gradient aggregation)

**CoCoI -- Coded Cooperative Inference (WiOpt 2025)** [Recent]
- Applies coded computation specifically to distributed CNN inference
- Splits convolutional layers accounting for data dependencies
- Reduces inference latency by up to 34.2% under stragglers/failures
- First system to adapt coded computation to high-dimensional inference workloads

### 2.3 Key Limitation of Batch-Processing Approaches

All the above approaches are designed for batch or offline workloads where:
- Tasks are idempotent and re-executable
- Latency tolerance is in minutes/hours, not milliseconds
- The system optimizes for job completion time, not per-request SLO compliance
- No dynamic strategy selection: each system uses a single fixed approach

---

## 3. Inference Serving Systems

### 3.1 General ML Inference Serving

**Clipper (NSDI 2017)** [Crankshaw et al.]
- General-purpose low-latency prediction serving system from UC Berkeley
- Key straggler mitigation: bounded-latency predictions for model ensembles
- Instead of waiting for all models, enforces a latency deadline and uses available predictions
- Transforms straggler latency cost into accuracy reduction (smaller effective ensemble)
- Architecture: model containers + model selection layer with adaptive batching
- Relevant insight: explicitly trades accuracy for latency under stragglers

**Clockwork (OSDI 2020)** [Gujarati et al.]
- Exploits the deterministic nature of DNN inference execution times
- Centralized controller schedules requests only if confident SLO can be met
- "Consolidating choice" principle: removes reactive/best-effort mechanisms
- Achieves 100ms latency target for 99.997% of requests across thousands of models
- Approach: eliminates variability by design rather than mitigating it
- Limitation: assumes predictable execution; real-world GPU performance degradation (thermal throttling) violates this assumption

**TensorFlow Serving (2016)** [Olston et al.]
- Production-grade serving from Google; focus on model versioning and batching
- Uses load balancing and request queuing but no explicit straggler mitigation
- Relies on infrastructure-level redundancy (Kubernetes, load balancers)

**NVIDIA Triton Inference Server**
- Multi-framework, multi-GPU serving platform
- Dynamic batching and concurrent model execution
- Health monitoring and model readiness checks
- No built-in straggler detection; relies on orchestration layer (Kubernetes) for node health

### 3.2 LLM Serving Systems

**Orca (OSDI 2022)** [Yu et al.]
- Iteration-level scheduling for transformer-based generative models
- Continuous batching: dynamically adds/removes requests each iteration
- No explicit straggler handling; designed for single-node GPU serving

**vLLM (SOSP 2023)** [Kwon et al.]
- PagedAttention for efficient KV cache memory management
- Near-zero memory waste; enables higher throughput via better batching
- Fault tolerance: relies on external orchestration (Kubernetes restart policies)
- No built-in mechanism for detecting or handling slow GPUs

**DistServe (OSDI 2024)** [Zhong et al.]
- Disaggregates prefill and decode phases onto separate GPU pools
- Optimizes goodput (requests meeting SLO / total requests)
- Enables heterogeneous hardware (e.g., H100 for prefill, A100 for decode)
- No explicit slow-node mitigation; disaggregation implicitly helps by specializing workload

**Splitwise (ISCA 2024, Best Paper)**
- Concurrent with DistServe; also disaggregates prefill/decode
- Uses heterogeneous hardware for energy efficiency
- Phase-aware placement can implicitly route around degraded nodes

**ServerlessLLM (OSDI 2024)** [Fu et al.]
- Low-latency serverless inference for LLMs
- Fast checkpoint loading and migration
- Could enable rapid replacement of slow instances, though not its primary design goal

**AlpaServe (OSDI 2023)**
- Statistical multiplexing of model parallelism for inference
- Trades parallelism overhead for reduced latency via resource sharing
- No straggler-specific mechanisms

### 3.3 Speculative Decoding (Distinct from Speculative Execution)

Note: "speculative execution" in LLM inference refers to speculative decoding -- a technique for faster autoregressive generation, not for straggler mitigation. This is an important distinction.

**Speculative Decoding** [Leviathan et al., 2023; Chen et al., 2023]
- Uses a smaller draft model to generate candidate tokens verified by the target model
- Reduces latency by parallelizing verification of multiple draft tokens
- Not related to straggler mitigation; focuses on single-request speedup

**WISP (2025)**
- Distributed speculative LLM serving at the edge
- SLO-aware batching that accounts for "verification interference" (head-of-line blocking from heterogeneous verification requests)
- Identifies "Wasted Drafting Time" as a key overhead metric
- Relevant to heterogeneous performance handling but not fail-slow mitigation

**AdaSpec (2025)**
- Adaptive speculative decoding with SLO awareness
- Dynamically adjusts speculation length based on system load and SLO requirements
- Shows that aggressive speculation can degrade performance at high load (up to 49.3% slower)

---

## 4. Straggler Mitigation in Training (Related Work)

**FALCON (2024)** [Recent]
- Straggler detection and mitigation for large-scale hybrid-parallel training (10,000+ GPUs)
- Non-intrusive, framework-agnostic detection of computation and communication fail-slows
- Multi-level mitigation mechanism (not single-strategy)
- Production deployment: 99%+ detection accuracy; mitigates training slowdown by 60.1%
- Finding: fail-slows last from tens of seconds to nearly 10 hours; collectively delay average job completion by 1.34%

**Malleus (SIGMOD 2025)**
- Straggler-resilient hybrid parallel training via malleable data and model parallelization
- Dynamically adjusts parallelism strategy when stragglers are detected

**Adaptra (2025)**
- Pipeline adaptation for straggler resilience in distributed training
- Inflight pipeline refactoring without stopping training

---

## 5. Load Balancing for Heterogeneous/Degraded Nodes

### 5.1 Classical Approaches

**Power of Two Choices** [Mitzenmacher, 2001]
- Random selection of two servers; route to less loaded one
- Exponentially reduces maximum load compared to random assignment
- Does not account for heterogeneous processing speeds

**Weighted Round Robin**
- Assigns weights proportional to server capacity
- Static weights fail to adapt to runtime performance degradation
- Some implementations periodically update weights based on observed latency

**Join-Shortest-Queue (JSQ) and Variants**
- Routes to server with shortest queue
- Optimal for homogeneous servers; suboptimal when servers have different speeds

### 5.2 Adaptive and Performance-Aware Approaches

**Performance-Aware Load Balancing for Inference**
- Profiles instance performance under mixed workloads
- Dynamically routes requests based on observed latency/throughput
- Accounts for GPU hardware heterogeneity (e.g., A100 vs V100: 1.7x speed difference)

**ML-Based Adaptive Routing**
- Uses historical traffic patterns and performance metrics to predict latency
- Directs requests to servers with predicted lowest latency
- Open research: energy-aware scheduling, heterogeneous hardware utilization

**NSGA-II-Based Routing (2025)**
- Multi-objective optimization for inference routing across cloud-edge LLM instances
- Balances response quality, response time, and inference cost
- Adapts to request heterogeneity and node diversity

### 5.3 Power-Aware Serving

**mu-Serve (USENIX ATC 2024)** [Qiu et al.]
- Power-aware DNN model serving with dynamic GPU frequency scaling
- Achieves 1.2--2.6x power savings without SLO violations
- Key mechanism: operator-level profiling of GPU frequency sensitivity
- Includes speculative request scheduler with proxy models
- Relevant: GPU frequency scaling is both a power-saving tool and a source of performance heterogeneity (thermal throttling causes involuntary frequency reduction)

---

## 6. Industry Practices for Handling Slow Inference Nodes

### 6.1 GPU Health Monitoring (Industry)

**Modal (20,000+ GPUs)** [Blog Post, 2025]
- Weekly active GPU health checks:
  - NVIDIA DCGM diagnostics (level 2)
  - GPUBurn/GPU-fryer stress tests
  - Local NCCL all-reduce tests for NVLink/NVSwitch validation
- Detects hardware clock slowdowns (HW_SLOWDOWN, HW_POWER_BRAKE)
- Finding: some cloud GPUs run at 90C+; FLOP/s degrades starting at mid-70s C

### 6.2 Cloud Provider Approaches

**AWS**
- Default metrics cover CPU/network; GPU requires custom monitoring via nvidia-smi/NVML
- CloudWatch custom metrics for GPU utilization, temperature, power draw
- Relies on instance replacement rather than in-place mitigation
- Auto Scaling groups can terminate and replace underperforming instances

**Google Cloud**
- Cloud Run GPU best practices: warns against over-subscription causing GPU contention
- Recommends monitoring request queue depths and latency percentiles
- Troubleshooting guide for compute performance issues
- No built-in slow-instance detection for inference workloads

**General Cloud Pattern**
- Detection: external monitoring + health checks + periodic benchmarks
- Mitigation: drain and replace the instance (coarse-grained)
- No graduated response based on severity
- Kubernetes-based orchestration handles node failures but not slow nodes well

### 6.3 Kubernetes and Orchestration

- Liveness/readiness probes can detect unresponsive nodes but not slow ones
- Pod disruption budgets manage availability during replacements
- Custom metrics-based autoscaling (HPA) can react to latency increases
- No native support for "this node is 30% slower than peers"

---

## 7. Research Gap Analysis

### 7.1 What Exists

| Aspect | Existing Work | Limitation |
|--------|--------------|------------|
| Fail-slow detection | IASO, Perseus, ADR | Detection only; mitigation is binary (reboot/shutdown) or delegated to system |
| Straggler mitigation (batch) | LATE, Mantri, Dolly, coded computing | Designed for batch jobs; single fixed strategy per system |
| Inference serving | Clipper, Clockwork, vLLM, Triton | Focus on normal operation; limited/no straggler-specific mechanisms |
| LLM disaggregation | DistServe, Splitwise | Implicitly helps via workload specialization; no explicit slow-node handling |
| Training stragglers | FALCON, Malleus, Adaptra | Training-specific; not applicable to latency-sensitive serving |
| Load balancing | Power-of-two-choices, weighted RR | Static or slowly adaptive; not severity-aware |
| Tail latency | Hedged requests, tied requests | Generic technique; no integration with fault severity assessment |
| Industry | GPU health checks, instance replacement | Coarse-grained; no graduated in-place response |

### 7.2 The Gap

**No existing work addresses adaptive, multi-strategy mitigation for slow faults in inference serving based on fault severity.**

Specifically, the gap lies at the intersection of:

1. **Severity-aware strategy selection**: Current systems use a single fixed response (IASO: reboot/shutdown; MapReduce: speculative execution; Cloud: replace instance). No system dynamically selects among multiple strategies (speculation, load shedding, isolation) based on how slow a node actually is.

2. **Inference-specific constraints**: Batch processing research (LATE, Mantri) is not applicable to millisecond-scale SLO-bound inference. LLM serving research (vLLM, DistServe) focuses on throughput/memory optimization, not degraded-node handling.

3. **Graduated response preserving capacity**: Simply isolating a slow node wastes its remaining capacity. Simply continuing to use it violates SLOs. The optimal response depends on the severity of degradation, remaining system capacity, and distance to SLO.

4. **Combined strategy space**: No work explores the strategy space of {speculative execution + load shedding + isolation} together, with a decision framework for when to apply each.

### 7.3 Why This Matters

- ADR's "danger zone" finding shows that slow faults have a nonlinear impact -- small severity increases can cause dramatic performance drops
- Inference workloads have strict latency SLOs (unlike batch processing)
- GPU performance degradation (thermal throttling, memory pressure) creates exactly the kind of graduated slowdown that demands graduated response
- Cloud inference deployments are large enough that slow nodes are statistically inevitable

---

## 8. Summary of Key References

| Paper | Venue | Year | Relevance |
|-------|-------|------|-----------|
| Dean & Barroso, "The Tail at Scale" | CACM | 2013 | Foundational: hedged/tied requests for tail latency |
| Zaharia et al., LATE Scheduler | OSDI | 2008 | Speculative execution in heterogeneous clusters |
| Ananthanarayanan et al., Mantri | OSDI | 2010 | Cause-aware straggler mitigation in MapReduce |
| Ananthanarayanan et al., Dolly | NSDI | 2013 | Full task cloning for small jobs |
| Crankshaw et al., Clipper | NSDI | 2017 | Bounded-latency prediction serving with straggler tolerance |
| Panda et al., IASO | ATC | 2019 | Fail-slow detection/mitigation at scale (39K nodes) |
| Gujarati et al., Clockwork | OSDI | 2020 | Predictable DNN serving via deterministic scheduling |
| Yu et al., Orca | OSDI | 2022 | Iteration-level scheduling for generative models |
| Lu et al., Perseus | FAST | 2023 | Non-intrusive fail-slow detection for storage |
| Kwon et al., vLLM | SOSP | 2023 | Efficient LLM serving with PagedAttention |
| Zhong et al., DistServe | OSDI | 2024 | Prefill-decode disaggregation for LLM serving |
| Splitwise | ISCA | 2024 | Heterogeneous hardware for disaggregated LLM serving |
| Fu et al., ServerlessLLM | OSDI | 2024 | Serverless LLM inference with fast migration |
| Qiu et al., mu-Serve | ATC | 2024 | Power-aware model serving with GPU frequency scaling |
| FALCON | arXiv | 2024 | Multi-level straggler mitigation for distributed training |
| Lu et al., ADR | NSDI | 2025 | Adaptive fail-slow handling with danger zone discovery |
| Malleus | SIGMOD | 2025 | Malleable parallelism for straggler-resilient training |
| CoCoI | WiOpt | 2025 | Coded computation for distributed inference |

---

## 9. Conclusion: Position of Our Work

Our proposed research fills a clear gap by:

1. **Targeting inference serving** -- a latency-sensitive workload where stragglers directly violate SLOs, unlike batch processing where they merely delay completion
2. **Defining a multi-strategy space** -- speculative execution, load shedding, and isolation as complementary strategies with different cost/benefit profiles
3. **Introducing severity-aware dynamic selection** -- using fault severity, system capacity headroom, and SLO distance as inputs to a strategy selection framework
4. **Leveraging ADR's danger zone insight** -- the nonlinear relationship between fault severity and performance degradation motivates graduated (not binary) response

This positions our work at the intersection of fail-slow fault research (IASO/Perseus/ADR), straggler mitigation (LATE/Mantri/FALCON), and inference serving systems (Clipper/Clockwork/vLLM), addressing a gap that none of these lines of work has tackled.
