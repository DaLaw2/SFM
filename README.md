# Capacity-Theoretic Limits of Slow Fault Mitigation Under P2C Routing

Research project investigating slow fault mitigation in distributed systems with Power-of-Two-Choices (P2C) load balancing. Includes a SimPy discrete-event simulator, a JAX GPU-accelerated batch simulator, and LaTeX papers (English/Chinese).

## Key Results

1. **Operating Envelope**: Maximum tolerable fault fraction is $f_{\max} = 1 - L/U$, where $L$ is load factor and $U$ is the utilization ceiling derived from M/D/1 queueing theory. No fitting parameters required.

2. **Severity Non-Monotonicity**: The worst tail latency occurs not at the highest slowdown, but at a critical severity $s^* = fq/((1-q)(N-f))$. Above $s^*$, P2C self-isolates faulty nodes via queue-depth avoidance.

3. **SHED–P2C Complementarity**: Under P2C, explicit weight reduction (SHED) and full isolation produce nearly identical P99 (gap < 2ms). Detection speed dominates strategy selection — the specific response mechanism is inconsequential.

## Project Structure

```
simulator/               # Core SimPy discrete-event simulator
simulator_gpu/           # JAX GPU-accelerated batch simulator
experiments/             # Experiment scripts (s1–s15) and runner
  results/               # Output CSVs and plots per scenario
research/                # Research documents
  findings/              # Experiment findings (v01–v19)
  discussions/           # Expert panel discussions
  surveys/               # Literature surveys
decisions/               # Architecture decision records (DR-00x)
docs/                    # Technical design docs
archive/                 # Versioned code snapshots (zips only)
paper/                   # LaTeX papers
  figures/               # Shared figures
  en/                    # English paper (pdflatex)
  zh/                    # Chinese paper (xelatex)
```

## Quick Start

```bash
# Run a single experiment
uv run -m experiments.s1_severity_sweep

# Results appear in experiments/results/s1_severity_sweep/
```

## Compiling the Papers

Requires MiKTeX (or equivalent TeX distribution).

```bash
# English paper (pdflatex)
cd paper/en
pdflatex main && bibtex main && pdflatex main && pdflatex main

# Chinese paper (xelatex, requires CJK fonts)
cd paper/zh
xelatex main && bibtex main && xelatex main && xelatex main
```

## Navigation

| I want to... | Look here |
|---|---|
| Understand the simulator | `docs/overview.md` |
| See experiment results | `research/findings/` |
| Read expert discussions | `research/discussions/` |
| Check design decisions | `decisions/DR-*.md` |
| Read the paper (EN) | [`paper/en/main.pdf`](paper/en/main.pdf) |
| Read the paper (ZH) | [`paper/zh/main.pdf`](paper/zh/main.pdf) |
