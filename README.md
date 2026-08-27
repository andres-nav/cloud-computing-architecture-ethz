# Cloud Computing Architecture — Semester Project (ETH Zurich)

Co-scheduling a latency-critical service (memcached) alongside throughput-oriented batch
analytics (7 PARSEC / SPLASH-2x benchmarks) on a Google Cloud Kubernetes cluster, so that
batch makespan is minimized while memcached never violates its tail-latency SLO.

The cluster is provisioned with [kops](https://kops.sigs.k8s.io/), load is generated with
[memcache-perf (mcperf)](https://github.com/shaystrong/memcache-perf), and interference is
injected with [iBench](https://github.com/stanford-mast/iBench). Parts 1–2 characterize the
workloads; Parts 3–4 build the schedulers.

> Group 012 solution for ETH Zurich's Cloud Computing Architecture course. The course
> handout is not redistributed here; follow the official project description.

## The parts

| Part | What it does |
|------|--------------|
| `part1` | Interference characterization. Runs memcached alone and under each of 6 iBench microbenchmarks (cpu, l1d, l1i, l2, llc, membw), sweeping QPS and measuring p95 latency. Finding: CPU / L1i saturation is catastrophic; memory bandwidth interference is harmless. |
| `part2` | PARSEC scaling and interference sensitivity. 2a runs each of 7 jobs alone and under each interference type; 2b measures thread-count scaling (1, 2, 4, 8 threads). Produces the speedup data that feeds the scheduler design. |
| `part3` | Static, dependency-aware co-scheduling policy (graded). Hand-crafted node placement, core pinning (`taskset`), thread counts, and a job-dependency DAG, executed by a multithreaded Kubernetes launcher. Holds memcached p95 ≤ 1 ms at 30K QPS with **zero SLO violations** and ~220 s makespan (vs a ~330 s baseline). |
| `part3-openevolve` | Research extension: an **LLM autonomously discovers** the Part-3 policy using the [OpenEvolve](https://github.com/codelion/openevolve) evolutionary program-synthesis framework. Each candidate is scored by a **real-hardware evaluator** that deploys it to the live cluster, drives 30K QPS, launches the batch jobs, and returns an SLO-penalized makespan fitness. The best evolved policy is ported back to `part3/policies/openevolve-best.yaml`. |
| `part4` | Dynamic single-node controller (graded). No Kubernetes: memcached runs bare-metal (CPU affinity via `taskset`), batch jobs run as Docker containers on one 4-core VM. As offered load sweeps 5K→125K QPS, the controller continuously repartitions cores between memcached and one batch job at a time, using CPU-utilization feedback with hysteresis to hold p95 ≤ 0.8 ms. |

## Key source

- `part3/launcher.py` — Kubernetes launcher: parses a policy YAML, builds a job-dependency
  DAG from `# AFTER <job>` annotations, launches jobs in gated threads, watches pod phases,
  and validates the policy (7 jobs, no core overlap with memcached, no cycles).
- `part3/policies/` — the co-scheduling policies (per-author variants + `openevolve-best.yaml`).
- `part3-openevolve/initial_program.py`, `evaluator.py`, `evaluator_kr8s.py` — the evolvable
  `generate_schedule()` seed and the real-hardware fitness evaluators.
- `part4/controllers/` — the dynamic controllers (`docker` SDK + `psutil`); the policy surface
  is `decide_memcached_cores` / `decide_batch_allocation` / `decide_next_job`.
- `part4/monitor_cpu.py`, `scripts/scheduler_logger.py` — per-core utilization logger and the
  shared event logger.
- `interference/`, `parsec-benchmarks/` — the iBench and PARSEC Kubernetes manifests.
- `report/` — LaTeX source of the project report; `part*/plots.ipynb` — the analysis notebooks.

## Running it

This targets a live GCP account and a kops-provisioned Kubernetes cluster, so it is not
runnable as-is without that infrastructure. A [Nix](https://nixos.org/) dev shell with the
required tooling (kubernetes, kops, google-cloud-sdk, python3) is provided:

```sh
nix develop
```

Each part has its own `Makefile` and `README.md`. Set your GCS state-store bucket via the
`ETHID` variable (buckets are named `gs://cca-eth-2026-group-012-<ethid>/`), then, for example:

```sh
cd part1
make setup ETHID=<your-ethid>   # create → deploy → validate the cluster
make start-memcached
```

## Authors

Group 012 — Andres Navarro Pedregal, Magdalena Heeg, Oliver Bergqvist. Systems Group,
Department of Computer Science, ETH Zurich.
