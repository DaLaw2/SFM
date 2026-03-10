# Project: Slow Fault Mitigation

## Language Rules

- All code, comments, commit messages, and documentation: **English**
- Conversation with the user: **Traditional Chinese (繁體中文)**

## Environment

- Python 3.14, managed by uv — use `uv run <command>`
- Platform: Windows 11, bash shell
- LaTeX: MiKTeX
  - English (`paper/en/`): `pdflatex -interaction=nonstopmode main.tex && bibtex main && pdflatex -interaction=nonstopmode main.tex && pdflatex -interaction=nonstopmode main.tex`
  - Chinese (`paper/zh/`): uses `xelatex` (for xeCJK): `xelatex -interaction=nonstopmode main.tex && bibtex main && xelatex -interaction=nonstopmode main.tex && xelatex -interaction=nonstopmode main.tex`
  - Figures in `paper/figures/`, referenced without `figures/` prefix (graphicspath handles it)

## Research Workflow

Each iteration follows this cycle:

### 1. Modify Code
- Edit simulator (`simulator/`, `simulator_gpu/`) or experiments (`experiments/`)
- Keep changes focused on the current research question

### 2. Code Review
- Launch **Agent Teams** (parallel): e.g., correctness reviewer, edge-case reviewer, consistency reviewer
- Each agent independently audits the changes and reports findings
- Fix all high/medium severity findings before proceeding

### 3. Run Experiments
- **Max 1 agent** to run experiments sequentially: `uv run -m experiments.s<N>_<name>` (simulation is multi-threaded and saturates all CPU cores)
- S1 timeout: 10 min (550 jobs). Others: 5 min each
- Results land in `experiments/results/s<N>_<name>/`

### 4. Analyze and Document
- Launch **Agent Teams** (parallel) to analyze results from different perspectives: e.g., queueing theory, systems architecture, experimental methodology
- Synthesize agent reports into `research/findings/v<NN>-<slug>.md` (zero-padded for v01–v09)
- Include: context, data tables, root cause analysis, next research gaps

### 5. Archive
- Create zip directly: `archive/v<N>_<slug>.zip` containing `simulator/` and `experiments/` (excluding `__pycache__/`)
- **Only keep the zip** — no uncompressed directories in archive/

### 6. Commit and Push
- **Always push immediately after every commit** — no local-only commits
- Tag milestone commits: `git tag v<N>-<slug>`

### 7. Auto-Iterate (when user requests)
- Use the expert analysis from step 4 to determine the next research question
- If experts agree on direction → return to step 1 automatically
- If experts disagree → launch Agent Teams to debate and resolve, then proceed
- Stop and consult the user when: results are surprising, a major pivot is needed, or resources (time/compute) are a concern

## Project Structure

```
simulator/               # Core SimPy simulator
  config.py              # SimConfig, FaultConfig, StrategyConfig
  run.py                 # run_simulation() entry point
  core/                  # SimPy components (worker, balancer, generator, speculation, recovery)
  control/               # Control plane (monitor, detector, selector, AIMD)
  fault/                 # Fault injection (injector, patterns)
  metrics/               # Metrics collection
simulator_gpu/           # JAX GPU-accelerated batch simulator
  run.py                 # run_simulation_gpu(), run_batch_gpu()
  state.py               # SimState pytree (NamedTuple)
  config.py              # GPUConfig (dt, buffer sizes)
  kernels/               # JAX kernels (arrivals, routing, service, queue, fault)
  control/               # (Phase 4) GPU control plane
experiments/             # Experiment scripts and runner
  results/               # Output CSVs and plots per scenario
research/                # Research documents, organized by type
  findings/              # Experiment findings: v<NN>-<slug>.md
  discussions/           # Expert panel discussions: v<NN>-<topic>.md
  surveys/               # Literature surveys and early design explorations
decisions/               # Architecture decision records (DR-00x)
docs/                    # Technical design docs and guides
archive/                 # Versioned code snapshots (zips only)
paper/                   # LaTeX papers
  figures/               # Shared figures (both languages)
  en/                    # English paper
  zh/                    # Chinese paper
```

## Naming Conventions

- **Findings:** `research/findings/v<NN>-<slug>.md`
- **Discussions:** `research/discussions/v<NN>-<topic>.md`
- **Surveys:** `research/surveys/<topic>.md` (no version prefix)
- **Decisions:** `decisions/DR-<NNN>-<slug>.md`
- **Archives:** `archive/v<N>_<slug>.zip`
- **Experiments:** `experiments/s<N>_<name>.py`, results in `experiments/results/s<N>_<name>/`
