# Survey: Slow Fault Modeling and Simulation Methods

## 1. How Existing Papers Model Slow Faults

### 1.1 Fail-Slow at Scale (Gunawi et al., USENIX FAST 2018)

The foundational taxonomy paper. Analyzed **114 fail-slow hardware incidents** from **14 institutions** (including Pure Storage, NetApp, Huawei, Twitter, Los Alamos National Laboratory).

**Key findings on fault characteristics:**
- All major hardware types exhibit fail-slow: disk, SSD, CPU, memory, network
- Faults convert between forms (e.g., a dead power supply throttled CPUs by 50%)
- A memory card operating at 25% of normal speed caused cascading failures

**How slowness manifests (4 patterns):**
1. **Permanent slowdown** -- sustained reduced performance
2. **Fluctuating performance** -- alternating between normal and degraded states
3. **Partial degradation** -- some device sections maintain full performance while others slow
4. **Periodic unavailability** -- intermittent reboots or hangs

**Root cause categories:**
- Internal hardware: device wear, firmware bugs, partial component failures
- External/environmental: temperature (failed cooling, clogged filters), power (defective supplies, insufficient capacitors), configuration (BIOS errors, PCIe mapping), vibration, cosmic events

**Detection timeline (severity proxy):**
| Detection time | Percentage |
|----------------|------------|
| Minutes        | 1%         |
| Hours          | 13%        |
| Days           | 13%        |
| Weeks          | 11%        |
| Months         | 17%        |
| Unknown        | 45%        |

**Gap:** No formal severity classification or quantitative slowdown model. Detection relied on ad-hoc methods; S.M.A.R.T. data deemed "insufficient to act upon."

**Reference:** Gunawi et al., "Fail-Slow at Scale: Evidence of Hardware Performance Faults in Large Production Systems," USENIX FAST 2018 / ACM ToS 2018.

---

### 1.2 IASO (Panda et al., USENIX ATC 2019)

Nutanix production framework deployed across **39,000 nodes** for 1.5+ years.

**Fault model:**
- Fail-slow = "hardware or software component still functional (not fail-stop) but in much lower performance than expected"
- No explicit severity levels or parametric model
- Binary outcome: detected as slow or not

**Detection approach:**
- **Peer-based comparison**: compares a node's timeout signals against its peers
- Converts software timeout signals into a stable fail-slow metric
- Can isolate a slow node within minutes
- Annual fail-slow failure rate in production: **1.02%**

**Mitigation strategies (only 2 options):**
1. Reboot the slow node
2. If reboot doesn't help, shutdown

**Quantitative results:** Caught **232 fail-slow incidents** in a 7-month period.

**Limitations for our work:**
- Only node-level detection granularity
- Intrusive (requires source code modification)
- No graduated response -- only reboot or shutdown
- No parametric severity model

**Reference:** Panda et al., "IASO: A Fail-Slow Detection and Mitigation Framework for Distributed Storage Services," USENIX ATC 2019.

---

### 1.3 Perseus (Lu et al., USENIX FAST 2023, Best Paper)

Alibaba Cloud storage system. Monitoring **248K drives** over 10 months.

**Fault model -- drive-level latency-throughput regression:**
- Models the expected relationship between latency and throughput per drive
- Fail-slow = deviation from the expected latency-throughput curve

**Four-step detection process:**
1. **Outlier detection** using DBScan + PCA on raw latency-throughput data
2. **Regression modeling** on non-outlier data points (fits expected curve)
3. **Fail-slow event identification** via **slowdown ratio** = (actual latency) / (expected latency from regression)
4. **Risk evaluation** scanning the slowdown ratio time series for duration and severity patterns

**Severity quantification:**
- **Slowdown ratio**: upper bound of expected latency divided by actual drive latency
- Events classified by **duration x severity** (difference from expected performance)
- No discrete severity levels; continuous measure

**Dataset (publicly available):**
- **41,000 normal drives** + **315 verified fail-slow drives**
- ~100 billion data entries
- Monitoring daemon collects avg latency and throughput per drive every 15 seconds
- Available for research use (see Section 3 below)

**Root causes identified:**
- Software bugs (e.g., OS thread contention -- multiple drives sharing one I/O thread)
- Hardware defects
- Environmental factors

**Results:** Found 304 fail-slow cases; isolating them reduced node-level **P99.99 tail latency by 48%**.

**Reference:** Lu et al., "Perseus: A Fail-Slow Detection Framework for Cloud Storage Systems," USENIX FAST 2023.

---

### 1.4 ADR (Lu et al., USENIX NSDI 2025)

Paper: "One-Size-Fits-None: Understanding and Enhancing Slow-Fault Tolerance in Modern Distributed Systems"

**Core contribution -- the "danger zone" concept:**
- Almost all distributed systems have a **danger zone** where a small increase in fault severity causes **disproportionate performance degradation**
- This is a non-linear cliff effect, not gradual degradation
- Static thresholds cannot capture this because the danger zone shifts with workload

**ADR (Adaptive Detection and Recovery) mechanism:**
- Lightweight library integrated into system code
- Monitors response values and rate of change over time
- Uses **dynamic thresholds** instead of static ones
- Flags potential slow faults as those falling below the **99th percentile** of historical values
- Cross-validates by checking if response rate is continuously decreasing (prevents false positives)

**Slow fault characterization:**
- Fail-slow is rare but independent (248K SSDs monitored for 10 months yielded only 304 cases)
- Diverse severity, location, and other factors all affect impact
- Impact depends heavily on workload, deployment environment, and system configuration
- Varying cloud benchmarks, tail latency measurements, and fine-tuning configurations all affect tolerance

**Quantitative results:**
- ADR achieved **65% average reduction in performance degradation** vs. static thresholds

**Limitations for our work:**
- Cannot detect during system startup
- Requires developers to manually mark monitoring variables
- Mitigation relies on existing system mechanisms (no novel scheduling/strategy selection)
- No strategy-selection framework

**Reference:** Lu et al., "One-Size-Fits-None: Understanding and Enhancing Slow-Fault Tolerance in Modern Distributed Systems," USENIX NSDI 2025.

---

## 2. Simulation and Fault Injection Frameworks

### 2.1 Slooo -- Fail-Slow Fault Injection Framework
- **GitHub:** https://github.com/xlab-uiuc/slooo
- Xonsh-based (Python-Shell hybrid) fault injection framework for distributed systems
- **Injection methods:** delays, CPU contention, memory contention, disk contention, network contention
- **Tested on:** RethinkDB, MongoDB, TiDB (quorum-based systems)
- **Deployment:** pseudo-distributed (single machine) or Azure Cloud
- Designed to evaluate how quorum systems tolerate fail-slow faults
- Closely related to the NSDI 2025 ADR paper (same research group, UIUC)

### 2.2 Sieve -- FSH Bug Detection (USENIX ATC 2025)
- Fine-grained fail-slow hardware (FSH) fault injection
- Treats synchronized and timeout-protected I/O operations as candidate fault points
- **Context-sensitive injection:** avoids repeatedly injecting at the same point under the same context
- Found 6 bugs (2 confirmed) that other tools (FATE, Legolas) missed
- 4 of 7 FSH bugs only detectable by Sieve
- **Reference:** Dong et al., "Understanding and Detecting Fail-Slow Hardware Failure Bugs in Cloud Systems," USENIX ATC 2025.

### 2.3 Chaos Engineering Tools (Industry)

| Tool | Slowness Injection Capabilities |
|------|-------------------------------|
| **Chaos Mesh** (CNCF) | Pod failures, network latency, filesystem I/O delays; Kubernetes-native |
| **AWS FIS** | API throttling, instance termination, network latency, EBS I/O throttling, EFS latency |
| **Azure Chaos Studio** | VM reboots, network latency, disk failures |
| **Netflix Latency Monkey** | Artificial delays in service calls |
| **Toxiproxy** (Shopify) | TCP-level latency, bandwidth limits, connection drops |
| **Gremlin** | Resource (CPU/memory/disk), network (latency/packet loss), state faults |

**Key insight:** These tools can inject slowness but lack **parametric severity models** -- they inject fixed delays or resource contention, not graduated "percentage of normal performance" degradation.

### 2.4 Network/Cloud Simulators

| Simulator | Relevance to Slow Fault Research |
|-----------|--------------------------------|
| **ns-3** | Discrete-event network simulator; can model link degradation, latency variation; supports up to 10^9 nodes; no built-in slow-fault model |
| **CloudSim** | Cloud datacenter simulation (VM provisioning, energy); no native slow-fault support |
| **Astra-Sim** (Meta) | DNN training/inference network simulator; extended in RAPID-LLM with congestion-aware routing and faulty link modeling |
| **Custom discrete-event** | Most slow-fault papers use custom simulators tailored to their specific system |

**Gap:** No general-purpose simulator exists that natively supports parametric slow-fault modeling with configurable severity distributions.

---

## 3. Real-World Traces and Datasets

### 3.1 Perseus / Alibaba Fail-Slow Dataset (Primary public dataset)
- **Scale:** 41,000 normal drives + 315 verified fail-slow drives
- **Volume:** ~100 billion data entries
- **Collection:** Monitoring daemons recording avg latency and throughput per drive every 15 seconds
- **Duration:** 10 months of monitoring across 248K drives
- **Deployed since:** October 2021 for 300,000+ storage devices
- **Available for research use** (referenced in Perseus FAST 2023 paper)

### 3.2 FSA-Benchmark (UCSC OSPO / UChicago, 2024-2025)
- Reproduction and benchmarking of fail-slow detection algorithms on the Perseus dataset
- Evaluated 7 ML approaches: Autoencoder (3.33% failure rate, best precision), LSTM (28% failure rate, best for early detection), Cost-Sensitive Ranking, Multi-Prediction models
- **Code available** on GitHub (FSA_BENCHMARK repository)
- Jupyter notebooks for reproducing experiments on Chameleon testbed

### 3.3 Fail-Slow at Scale Dataset (FAST 2018)
- 114 incident reports from 14 institutions
- Qualitative/anecdotal rather than time-series traces
- Useful for taxonomy and root cause categorization, not for simulation input

### 3.4 Meta LLM Training Failure Data (Indirect)
- Meta reported **400+ unexpected job interruptions** during Llama 3 training on 16K GPUs
- Nearly half attributed to hardware/infrastructure failures
- Not publicly released as a dataset, but validates the scale of the problem

---

## 4. GPU/Inference-Specific Slow Fault Modeling

### 4.1 Thermal Throttling

**TAPAS (ASPLOS 2025)** -- Microsoft Research:
- First thermal- and power-aware scheduling for LLM inference clusters
- GPUs have a max safe temperature threshold; exceeding it triggers hardware throttling (reduced core voltage and frequency)
- Existing schedulers increase thermal throttling probability by **10x**, causing up to **34.2% performance degradation**
- Thermal model: piecewise polynomial regression predicting GPU temperature from inlet temperature and load (MAE < 1 deg C)
- Adjustable parameters: GPU frequency, batch size, model parallelism, quantization, model size
- Results: reduces throttling events by 97% (thermal) and 99% (power); enables 40% additional capacity
- **Reference:** Qiu et al., "TAPAS: Thermal- and Power-Aware Scheduling for LLM Inference in Cloud Platforms," ASPLOS 2025.

**Key modeling insight for simulation:**
- Thermal throttling can be modeled as: temperature rises with load over time -> once threshold exceeded -> frequency drops -> inference latency increases proportionally to frequency reduction
- The degradation is **continuous and progressive**, not a step function
- Mobile/edge: CPU frequency drops from 3GHz to 1GHz after ~2.5 minutes of continuous operation

### 4.2 Network Jitter in Distributed Inference

**RAPID-LLM (arXiv, Dec 2025):**
- Unified performance modeling framework for LLM training and inference on GPU clusters
- Couples DeepFlow frontend (generates hardware-aware operator-level execution traces) with extended Astra-Sim backend (multi-dimensional network with congestion-aware routing)
- Models **degraded and faulty links** explicitly
- Single soft-link faults injected at multiple locations to measure runtime degradation
- Predicts Llama inference step latency within **10.4%** of published measurements
- **Reference:** "RAPID-LLM: Resilience-Aware Performance analysis of Infrastructure for Distributed LLM Training and Inference," arXiv 2512.19606.

### 4.3 Straggler Mitigation in Inference

**CoCoI (WiOpt 2025):**
- Coded inference for CNN: splits convolutional layers with data dependency awareness, applies coding for redundancy
- Results determined once a **subset** of devices complete subtasks
- Reduces inference latency by up to **34.2%** vs. uncoded baselines under stragglers
- Tested on Raspberry Pi 4B testbed
- Formulates optimal splitting problem to minimize expected latency given straggler distribution
- **Reference:** Huang et al., "CoCoI: Distributed Coded Inference System for Straggler Mitigation," WiOpt 2025.

**PyTorch DDP Hierarchical SGD:**
- Built-in straggler mitigation for distributed training
- Detects idle threads and redirects work to support non-idle threads
- Available in PyTorch natively

### 4.4 Memory Pressure
- Less directly studied in inference context
- GPU memory pressure causes OOM or forces smaller batch sizes, indirectly increasing per-request latency
- Can be modeled as reduced effective batch size -> lower throughput

---

## 5. Severity Quantification Methods

### 5.1 Approaches Used in Literature

| Paper/System | Severity Metric | How Measured |
|-------------|----------------|-------------|
| **Perseus** | Slowdown ratio | actual_latency / expected_latency (from regression) |
| **ADR** | Dynamic percentile | comparison vs. 99th percentile of historical values |
| **IASO** | Binary (slow/not slow) | peer timeout comparison |
| **Fail-Slow at Scale** | Qualitative | incident reports, no formal metric |
| **TAPAS** | Temperature delta from threshold | piecewise polynomial regression |
| **Straggler literature** | Progress rate | task_progress / expected_progress (MapReduce-style) |

### 5.2 Common Quantification Dimensions

1. **Throughput drop ratio**: actual_throughput / baseline_throughput (e.g., node operating at 60% of normal)
2. **Latency inflation**: actual_latency / expected_latency (e.g., P99 latency 3x normal)
3. **Tail latency percentile**: P99, P99.9, P99.99 -- higher percentiles more sensitive to slow faults
4. **Duration x severity product**: how long and how severe (Perseus approach)
5. **SLO distance**: (current_latency - SLO_target) / SLO_target -- negative = within SLO, positive = violating

### 5.3 The Danger Zone (ADR/NSDI 2025)

The most important insight for severity modeling:
- Performance degradation is **non-linear** with respect to fault severity
- There exists a **danger zone** threshold where small severity increases cause cliff-like performance drops
- This threshold shifts dynamically with workload
- Implication: severity quantification must be **relative to the current operating point**, not absolute

---

## 6. Key Insights and Gaps for Our Research

### 6.1 What Exists
- **Detection** is well-studied (IASO, Perseus, ADR)
- **Taxonomy** of root causes is established (Fail-Slow at Scale)
- **Single-strategy mitigation** is common (reboot/shutdown, speculative execution)
- **Thermal-aware scheduling** for inference is emerging (TAPAS)
- **Fault injection tools** exist but lack parametric severity models
- **One public dataset** (Perseus/Alibaba) with real fail-slow traces

### 6.2 What's Missing (Opportunities for Our Work)

1. **No parametric slow-fault model for simulation**: Existing work uses real traces or binary injection. No paper provides a formal model like "inject X% slowdown with Y distribution over Z duration" suitable for systematic simulation studies.

2. **No multi-strategy selection framework**: All existing mitigation is single-strategy. No system dynamically chooses between speculative execution, load shedding, and isolation based on severity and system state.

3. **No inference-specific slow-fault simulator**: RAPID-LLM models link faults but not compute-side thermal throttling or memory pressure as gradual degradation. TAPAS models thermal effects but not as a general simulation framework.

4. **Danger zone is identified but not exploited**: ADR discovers the danger zone phenomenon but doesn't use it to drive strategy selection. This is exactly where our adaptive framework should operate.

5. **No SLO-aware strategy selection**: Existing work either ignores SLOs (straggler mitigation) or treats them as post-hoc evaluation metrics. No system uses SLO distance as a real-time input to strategy selection.

### 6.3 Recommended Modeling Approach for Our Simulation

Based on this survey, we recommend:

1. **Fault model**: Multiplicative slowdown factor `s in [1.0, infinity)` where `s=1.0` is normal and `s=2.0` means twice as slow. Apply to per-request processing time.

2. **Severity distribution**: Draw from empirical distributions based on Perseus data, or use parameterized distributions (e.g., log-normal for gradual degradation, step function for thermal throttling events).

3. **Temporal patterns**: Support the 4 patterns from Fail-Slow at Scale:
   - Permanent: constant `s` after onset
   - Fluctuating: `s` alternates between normal and degraded (modeled as on/off with configurable duty cycle)
   - Progressive: `s` increases over time (thermal throttling model)
   - Intermittent: random episodes of slowdown

4. **Danger zone modeling**: Define a system-level function mapping per-node slowdown to aggregate performance, with a configurable inflection point.

5. **Evaluation metrics**: P99/P99.9 latency, throughput, SLO violation rate, resource utilization overhead.

---

## References

1. Gunawi et al., "Fail-Slow at Scale: Evidence of Hardware Performance Faults in Large Production Systems," USENIX FAST 2018 / ACM ToS 2018.
2. Panda et al., "IASO: A Fail-Slow Detection and Mitigation Framework for Distributed Storage Services," USENIX ATC 2019.
3. Lu et al., "Perseus: A Fail-Slow Detection Framework for Cloud Storage Systems," USENIX FAST 2023. (Best Paper)
4. Lu et al., "One-Size-Fits-None: Understanding and Enhancing Slow-Fault Tolerance in Modern Distributed Systems," USENIX NSDI 2025.
5. Dong et al., "Understanding and Detecting Fail-Slow Hardware Failure Bugs in Cloud Systems," USENIX ATC 2025.
6. Qiu et al., "TAPAS: Thermal- and Power-Aware Scheduling for LLM Inference in Cloud Platforms," ASPLOS 2025.
7. "RAPID-LLM: Resilience-Aware Performance Analysis of Infrastructure for Distributed LLM Training and Inference," arXiv 2512.19606, Dec 2025.
8. Huang et al., "CoCoI: Distributed Coded Inference System for Straggler Mitigation," WiOpt 2025.
9. Song et al., "Reproduction Research of FSA-Benchmark," arXiv 2501.14739, Jan 2025.
10. Slooo Framework: https://github.com/xlab-uiuc/slooo
