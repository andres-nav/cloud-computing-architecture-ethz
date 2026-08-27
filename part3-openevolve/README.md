# Part 3.2 — OpenEvolve Scheduling Policy Discovery

Uses OpenEvolve to autonomously evolve a scheduling policy (including memcached
placement) via LLM, targeting minimum makespan while maintaining the memcached
SLO (p95 ≤ 1ms at 30K QPS).

## Prerequisites

```sh
# Create .env with your API key (gitignored)
echo 'OPENAI_API_KEY=<your-swissai-key>' > .env
```

## Workflow

```sh
# 0. Create virtualenv and authenticate
make venv
make gcloud-login

# 2. Cluster setup + build mcperf
make setup
make setup-mcperf

# 2. Run evolution (evaluator handles memcached + mcperf per iteration)
make run-evolve

# 3. Stop evolution at any time with Ctrl+C
#    Resume from checkpoint:
#    set -a && . .env && set +a && \
#    .venv/bin/openevolve-run --config config.yaml \
#      --checkpoint checkpoint/checkpoints/checkpoint_XXX \
#      -o checkpoint initial_program.py evaluator.py

# 4. Cleanup
make clean
```

## Files

| File                 | Purpose                                                             |
|----------------------|---------------------------------------------------------------------|
| `Makefile`           | Cluster setup + openevolve target                                   |
| `initial_program.py` | Evolvable scheduler (memcached + batch jobs)                        |
| `evaluator.py`       | Deploys memcached, starts mcperf, runs batch jobs, measures, scores |
| `config.yaml`        | OpenEvolve config: LLM model, system prompt, evolution params       |
| `results/`           | Per-iteration cluster measurements (committed)                      |
| `checkpoint/`        | OpenEvolve internal state for resuming runs (gitignored)            |

## How it works

Each OpenEvolve iteration:
1. LLM modifies `generate_schedule()` inside the EVOLVE-BLOCK
2. Evaluator deploys memcached with evolved placement
3. Starts mcperf measurement
4. Launches batch jobs via launcher
5. Waits for completion, parses makespan + p95
6. Cleans up everything (memcached, mcperf, batch jobs)
7. Score = makespan performance × SLO compliance → guides next evolution

## Timing

- Each iteration ≈ 8–12 min (memcached + mcperf setup + job execution)
- 50 iterations ≈ 7–10 hours of cluster time
- Start with `max_iterations: 15` in config.yaml for testing
