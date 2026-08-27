# Part 3 — Co-Scheduling Memcached and Batch Jobs

Co-schedules memcached (SLO: 1ms p95 at 30K QPS) with 7 PARSEC/SPLASH2x batch
jobs on a heterogeneous Kubernetes cluster. Goal: minimize batch job makespan
without violating the memcached latency SLO.

## Cluster

| Node | Type | Role |
|------|------|------|
| master | e2-standard-2 | kops control plane |
| node-a-8core | e2-standard-8 | batch jobs (8 cores) |
| node-b-4core | n2d-highcpu-4 | memcached + batch jobs (4 cores) |
| client-agent-a | e2-standard-2 | mcperf agent (2 threads) |
| client-agent-b | e2-standard-4 | mcperf agent (4 threads) |
| client-measure | e2-standard-2 | mcperf measurement (6 threads) |

## Workflow

```sh
# Set your policy for the entire session (if you open other terminals, make sure to run it also)
export POLICY=oliver-v1
export SSH_KEY="~/.ssh/cloud-computing"
export ETHID=ethid

# 0. Authenticate
make gcloud-login

# 1. Spin up cluster
make setup ETHID=$ETHID SSH_KEY=$SSH_KEY

# 2. Check IPs
make get-ips

# 3. Build mcperf on all client VMs
make setup-mcperf SSH_KEY=$SSH_KEY

# 4. Run everything (memcached + agents + mcperf + batch jobs × N runs)
make run-automate POLICY=$POLICY RUNS=3 SSH_KEY=$SSH_KEY

# 5. Delete cluster when done
make clean
```

### Manual workflow (if you prefer step-by-step)

```sh
# 4. Deploy memcached (waits until pod is Running)
make start-memcached POLICY=$POLICY

# 5. Start mcperf agents (background)
make run-agent-a
make run-agent-b

# 6. Start mcperf measurement (runs continuously in a separate terminal)
# OPEN A SEPARATE NEW TERMINAL FOR RUNNING THIS:
make run-mcperf POLICY=$POLICY

# NOTE: make sure only memcached is running (`-w` is for "watch mode". ctrl-c to get out)
kubectl get pods -w

## Repeat steps 7-10 for each run (3 times), or use `make run-automate` to automate.
# 7. Deploy batch jobs (handles dependencies automatically)
make run-policy POLICY=$POLICY

# 8. Collect results (verifies all 7 jobs completed and prints times)
make collect-results POLICY=$POLICY

# 9. Clean batch jobs for next run (memcached stays up)
make clean-jobs

# 10. Delete cluster when done
make clean
```

## Scheduling policies

Policies live in `policies/` as single YAML files containing memcached + all 7 batch jobs with node placement, core pinning, and thread counts.

- `policies/template.yaml`: blank template for new policies
- `policies/andres-v1.yaml`: Andres example hand-crafted policy

To run a specific policy, pass `POLICY=<name>` to any make target:

```sh
# All targets respect the POLICY variable (default: andres-v1)
make start-memcached POLICY=andres-v2
make run-mcperf POLICY=andres-v2
make run-automate POLICY=andres-v2 RUNS=3

# Or for individual steps:
make run-policy POLICY=andres-v2
make collect-results POLICY=andres-v2
```

To create a new policy, copy an existing one and adjust node selectors, `taskset` cores, and thread counts (`-n`).
