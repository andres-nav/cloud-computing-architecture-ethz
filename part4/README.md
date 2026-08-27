# Part 4 — Dynamic Co-Scheduling

Co-schedules 7 PARSEC/SPLASH2x batch jobs with a live memcached service on a
single 4-core VM. The controller dynamically adjusts CPU allocation to keep
memcached p95 latency ≤ 0.8 ms while completing batch jobs as fast as possible.

**Key difference from Parts 1–3:** no Kubernetes. memcached runs bare-metal
(CPU affinity via `taskset`); batch jobs run in Docker containers.

## Cluster

| Node            | Type                    | Role                                |
|-----------------|-------------------------|-------------------------------------|
| master          | n2-standard-2           | kops control plane                  |
| memcache-server | n2d-highmem-4 (4 cores) | memcached + batch jobs + controller |
| client-agent    | e2-standard-8           | mcperf load agent                   |
| client-measure  | n2-standard-2           | mcperf measurement                  |

## Workflow

```sh
# Set your controller for the session
export CONTROLLER=andres-v1

# 0. Authenticate
make gcloud-login

# 1. Spin up cluster
make setup [ETHID=your-eth-username]

# 2. Check IPs
make get-ips

# 3. Install software on all VMs (memcached, Docker, mcperf, controller)
make setup-all

# 4. Start mcperf agent (background on client-agent)
make run-agent

# 5. Run experiment (substitute with the question you're working on):
#    Q1:  make run-q1-all                          (no controller needed)
#    Q3:  make run-q3  (Terminal 1)  +  make run-controller  (Terminal 2)
#    Q4:  make run-q4  (Terminal 1)  +  make run-controller  (Terminal 2)

# 6. Collect results (substitute with the question):
#    Q1:  (collected automatically by run-q1-all)
#    Q3:  make collect-results Q=q3
#    Q4:  make collect-results Q=q4

# 7. Clean up between runs (Q3/Q4 only)
make clean-containers

# 8. Delete cluster when done
make clean
```

## Experiment shortcuts

| Target                          | Description                                       |
|---------------------------------|---------------------------------------------------|
| `make run-q1 THREADS=2 CORES=2` | Q1: single config sweep 5K→125K QPS               |
| `make run-q1-all`               | Q1a: all 9 thread/core configs automatically      |
| `make run-q3`                   | Q3: dynamic trace, seed=2345, interval=15s, 30min |
| `make run-q4`                   | Q4: dynamic trace, seed=2345, interval=5s, 30min  |

### Q1 — Static sweep (no controller)

```sh
# Run all 9 configs (T=1,2,3 × C=1,2,3), collects results automatically
make run-q1-all

# Or run a single config
make run-q1 THREADS=2 CORES=3
make collect-q1 THREADS=2 CORES=3
```

Results: `results/q1/T2_C3/<timestamp>/mcperf.txt`

### Q3 — Dynamic trace, 15s interval (with controller)

```sh
# Terminal 1: start trace first (so memcached is under load before batch jobs)
make run-q3

# Terminal 2: start controller (launches batch jobs)
make run-controller

# After both finish:
make collect-results Q=q3
make clean-containers
```

Results: `results/q3/<controller>/<timestamp>/`

### Q4 — Dynamic trace, 5s interval (with controller)

```sh
# Terminal 1: start trace first
make run-q4

# Terminal 2: start controller
make run-controller

# After both finish:
make collect-results Q=q4
make clean-containers
```

Results: `results/q4/<controller>/<timestamp>/`

## Controller

Controllers live in `controllers/` as Python files. Select one with `CONTROLLER=<name>`:

- `controllers/template.py` — blank template with TODO functions
- `controllers/andres-v1.py` — working controller

Three functions to implement:

- `decide_memcached_cores` — returns new core list for memcached based on CPU utilization
- `decide_batch_allocation` — returns `{job_name: [cores]}` for active batch jobs
- `decide_next_job` — returns `(job, cores)` for the next job to launch, or `None` to wait

After editing, push changes to the server with:
```sh
make setup-controller CONTROLLER=andres-v1
```

## Results structure

```
results/
├── q1/<timestamp>/
│   └── mcperf.txt
├── q3/<controller>/<timestamp>/
│   ├── mcperf.txt
│   ├── log<date>.txt      # scheduler job log
│   ├── controller.log     # controller stdout
│   └── controller.py      # copy of controller used
└── q4/<controller>/<timestamp>/
    ├── mcperf.txt
    ├── log<date>.txt
    ├── controller.log
    └── controller.py
```
