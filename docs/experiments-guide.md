# Experiments Guide

## Prerequisites

```bash
cd D:\Code\Other
pip install -e ".[plot]"
pip install scipy
```

Or if using the project's virtual environment:
```bash
.venv/Scripts/python.exe -m pip install scipy
```

Required packages: `simpy`, `numpy`, `pandas`, `matplotlib`, `scipy`.

## Running Experiments

Each experiment is a standalone script in `experiments/`:

```bash
# Run individual experiments
python experiments/s1_severity_sweep.py
python experiments/s2_progressive.py
python experiments/s3_flash_crowd.py
python experiments/s4_multi_node.py
python experiments/s5_fluctuating.py
python experiments/s6_cascade.py
python experiments/s7_recovery.py
```

Each script uses `ExperimentRunner` from `experiments/runner.py` and runs 5 baselines x 10 runs. Typical runtime is 5-15 minutes per experiment depending on duration and load.

## Experiment Descriptions

| Scenario | Script | Description | Duration | Load |
|----------|--------|-------------|----------|------|
| S1 | `s1_severity_sweep.py` | Sweep slowdown factor 1.0-10.0 on 1 node | 60s | 90% |
| S2 | `s2_progressive.py` | Progressive thermal throttling (beta=0.05) | 120s | 80% |
| S3 | `s3_flash_crowd.py` | Variable load (70%->95%->70%) with fault | 100s | 70-95% |
| S4 | `s4_multi_node.py` | 4 nodes fail simultaneously (random slowdowns) | 60s | 80% |
| S5 | `s5_fluctuating.py` | Oscillating fault (5s on / 5s off) | 120s | 80% |
| S6 | `s6_cascade.py` | 2 nodes fail at staggered times | 90s | 85% |
| S7 | `s7_recovery.py` | Temporary fault with node recovery | 100s | 80% |

## Output Structure

Each experiment writes results to `experiments/results/<scenario_name>/`:

```
experiments/results/s3_flash_crowd/
  raw_results.csv       # Per-run metrics (baseline, run_id, seed, p99, throughput, etc.)
  summary.csv           # Aggregated mean, 95% CI, min, max per baseline per metric
  metadata.json         # Experiment parameters (n_workers, load, duration, etc.)
  p99_comparison.png    # Bar chart: P99 latency by baseline
  throughput_comparison.png  # Bar chart: Throughput by baseline
```

S1 additionally produces `p99_vs_slowdown.png` and `throughput_vs_slowdown.png` (line plots across slowdown values).

## Interpreting Results

### raw_results.csv

One row per (baseline, run) combination. Key columns:
- `p99_latency`, `p95_latency`, `p50_latency`, `avg_latency`: in seconds
- `throughput`: requests/second
- `seed`: random seed for reproducibility

### summary.csv

Aggregated statistics per (baseline, metric). Columns:
- `mean`: mean across runs
- `ci_95`: 95% confidence interval half-width (Student's t)
- `min`, `max`: extreme values
- `slo_violation_fraction`: fraction of runs where P99 > 100ms

### Plots

- Bar charts show mean values with 95% CI error bars
- Red dashed line at 100ms marks the SLO target
- Baseline order: No Mitigation, Fixed Speculation, Fixed Shedding, Fixed Isolation, Adaptive

## Adding New Experiments

1. Create `experiments/s<N>_<name>.py`
2. Define a `fault_config_fn(seed) -> FaultConfig` that returns the fault setup
3. Configure `SimConfig` with desired parameters
4. Use `ExperimentRunner.run_all()` to execute
5. Call `generate_all_plots()` for standard plot generation

For variable load experiments, pass a `load_schedule` parameter (list of `(time, load_factor)` tuples) to `run_all()`.

## Baselines

Defined in `experiments/runner.py` as `DEFAULT_BASELINES`:

| Name | Mitigation | Config |
|------|------------|--------|
| `no_mitigation` | Off | N/A |
| `fixed_speculation` | On | theta_spec=0.1, theta_shed/iso=999 |
| `fixed_shedding` | On | theta_shed=0.1, theta_spec/iso=999 |
| `fixed_isolation` | On | theta_iso=0.3, theta_spec/shed=999 |
| `adaptive` | On | Default StrategyConfig |
