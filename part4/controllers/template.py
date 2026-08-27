#!/usr/bin/env python3
"""Part 4 scheduler: co-schedules memcached (taskset) and PARSEC jobs (Docker).

Usage: python3 controller.py [--log-dir DIR]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

import docker
import psutil

from scheduler_logger import Job, SchedulerLogger

# =============================================================================
# CONFIGURATION — modify this section
# =============================================================================

ALL_CORES = [0, 1, 2, 3]
POLL_INTERVAL = 2.0
MEMCACHED_MIN_CORES = 1
MEMCACHED_MAX_CORES = 3

# Job order: first job launched first. Reorder as needed.
# Adjust threads per job. SPLASH2x (radix, barnes) need power-of-2.
BATCH_JOBS = [
    {"name": "blackscholes",   "job_enum": Job.BLACKSCHOLES,   "image": "anakli/cca:parsec_blackscholes",   "suite": "parsec",   "program": "blackscholes",   "threads": 2},
    {"name": "canneal",        "job_enum": Job.CANNEAL,        "image": "anakli/cca:parsec_canneal",        "suite": "parsec",   "program": "canneal",        "threads": 2},
    {"name": "freqmine",       "job_enum": Job.FREQMINE,       "image": "anakli/cca:parsec_freqmine",       "suite": "parsec",   "program": "freqmine",       "threads": 2},
    {"name": "vips",           "job_enum": Job.VIPS,           "image": "anakli/cca:parsec_vips",           "suite": "parsec",   "program": "vips",           "threads": 2},
    {"name": "radix",          "job_enum": Job.RADIX,          "image": "anakli/cca:splash2x_radix",        "suite": "splash2x", "program": "radix",          "threads": 2},
    {"name": "streamcluster",  "job_enum": Job.STREAMCLUSTER,  "image": "anakli/cca:parsec_streamcluster",  "suite": "parsec",   "program": "streamcluster",  "threads": 2},
    {"name": "barnes",         "job_enum": Job.BARNES,         "image": "anakli/cca:splash2x_barnes",       "suite": "splash2x", "program": "barnes",         "threads": 2},
]


# TODO: implement your memcached scaling policy
def decide_memcached_cores(
    cpu_util: list, current_cores: list, memcached_cpu_pct: float
) -> list:
    """Return the new core list for memcached.

    Args:
        cpu_util: per-core utilization [0.0-1.0] for cores 0-3
        current_cores: current memcached core list, e.g. [0]
        memcached_cpu_pct: memcached CPU% (0-400 for 4 cores)
    """
    return current_cores


# TODO: implement your batch job core allocation
def decide_batch_allocation(
    active_jobs: list, pending_jobs: list, memcached_cores: list
) -> dict:
    """Return {job_name: [cores]} for active batch jobs.

    Args:
        active_jobs: list of running job dicts (has 'name', 'cores', etc.)
        pending_jobs: list of not-yet-started job dicts
        memcached_cores: current memcached core list
    """
    return {job["name"]: job["cores"] for job in active_jobs}


# TODO: implement your job launch policy
def decide_next_job(
    pending_jobs: list, active_jobs: list, memcached_cores: list
) -> tuple | None:
    """Return (job, cores) for the next job to start, or None to wait.

    Args:
        pending_jobs: jobs not yet started
        active_jobs: currently running jobs
        memcached_cores: current memcached core list
    """
    busy = {c for j in active_jobs for c in j["cores"]}
    free = [c for c in ALL_CORES if c not in memcached_cores and c not in busy]
    if free and pending_jobs:
        return pending_jobs[0], free
    return None


# =============================================================================
# SCHEDULER LOOP — do not modify below
# =============================================================================

def _read_proc_stat() -> list:
    rows = []
    with open("/proc/stat") as f:
        for line in f:
            if line.startswith("cpu") and line[3].isdigit():
                rows.append([int(x) for x in line.split()[1:]])
    return rows


def run_controller(log_dir: str = ".") -> None:
    os.makedirs(log_dir, exist_ok=True)
    os.chdir(log_dir)

    logger = SchedulerLogger()
    client = docker.from_env()

    memcached_pid = next(
        (p.pid for p in psutil.process_iter(["pid", "name"]) if p.info["name"] == "memcached"),
        None,
    )
    if memcached_pid is None:
        sys.exit("ERROR: memcached not running.")

    memcached_cores = [0]
    logger.job_start(Job.MEMCACHED, memcached_cores, 4)
    print(f"[memcached] pid={memcached_pid}")

    pending = [dict(j, cores=[], container=None) for j in BATCH_JOBS]
    active: list = []
    done: list = []

    # Clean up containers from previous runs
    for j in BATCH_JOBS:
        try:
            old = client.containers.get(j["name"])
            old.remove(force=True)
            print(f"[cleanup] removed stale container '{j['name']}'")
        except docker.errors.NotFound:
            pass

    try:
        while pending or active:
            b = _read_proc_stat()
            time.sleep(POLL_INTERVAL)
            a = _read_proc_stat()
            cpu_util = []
            for before, after in zip(b, a):
                total = sum(after) - sum(before)
                idle = after[3] - before[3]
                cpu_util.append(0.0 if total == 0 else 1.0 - idle / total)
            mem_cpu = psutil.Process(memcached_pid).cpu_percent(interval=1.0)
            monitor_msg = f"[monitor] {[f'{u:.0%}' for u in cpu_util]}  memcached={mem_cpu:.1f}%"
            print(monitor_msg)
            logger.custom_event(Job.SCHEDULER, monitor_msg)

            # Adjust memcached cores
            new_mem = decide_memcached_cores(cpu_util, memcached_cores, mem_cpu)
            if sorted(new_mem) != sorted(memcached_cores):
                subprocess.run(
                    ["sudo", "taskset", "-a", "-cp",
                     ",".join(str(c) for c in new_mem), str(memcached_pid)],
                    check=True, capture_output=True,
                )
                logger.update_cores(Job.MEMCACHED, new_mem)
                memcached_cores = new_mem
                print(f"[memcached] cores → {memcached_cores}")

            # Adjust batch job cores
            alloc = decide_batch_allocation(active, pending, memcached_cores)
            for job in active:
                new_cores = alloc.get(job["name"])
                if new_cores and sorted(new_cores) != sorted(job["cores"]):
                    job["container"].update(cpuset_cpus=",".join(str(c) for c in new_cores))
                    job["cores"] = new_cores
                    logger.update_cores(job["job_enum"], new_cores)
                    print(f"[{job['name']}] cores → {new_cores}")

            # Start next pending job
            result = decide_next_job(pending, active, memcached_cores)
            if result is not None:
                job, cores = result
                pending.remove(job)
                cmd = f"./run -a run -S {job['suite']} -p {job['program']} -i native -n {job['threads']}"
                job["container"] = client.containers.run(
                    image=job["image"], command=cmd,
                    cpuset_cpus=",".join(str(c) for c in cores),
                    detach=True, remove=False, name=job["name"],
                )
                job["cores"] = cores
                logger.job_start(job["job_enum"], cores, job["threads"])
                active.append(job)
                print(f"[{job['name']}] started on {cores}")

            # Detect completed jobs
            still_running = []
            for job in active:
                try:
                    job["container"].reload()
                    finished = job["container"].status == "exited"
                except docker.errors.NotFound:
                    finished = True
                if finished:
                    exit_code = 1
                    try:
                        exit_code = job["container"].attrs.get("State", {}).get("ExitCode", 1)
                        job["container"].remove()
                    except docker.errors.NotFound:
                        pass
                    logger.job_end(job["job_enum"])
                    if exit_code != 0:
                        print(f"[{job['name']}] FAILED (exit={exit_code})")
                        raise RuntimeError(f"{job['name']} failed with exit code {exit_code}")
                    done.append(job["name"])
                    print(f"[{job['name']}] finished")
                else:
                    still_running.append(job)
            active = still_running
            print(f"[scheduler] active={[j['name'] for j in active]}  done={done}")

    except (KeyboardInterrupt, RuntimeError) as e:
        print(f"\n[scheduler] stopping: {e}")
        for job in active:
            try:
                logger.job_end(job["job_enum"])
                job["container"].remove(force=True)
            except Exception:
                pass
    finally:
        logger.end()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-dir", default=".")
    run_controller(log_dir=parser.parse_args().log_dir)
