import argparse
import os
from functools import lru_cache
from docker import DockerClient
from itertools import chain
from docker.models.containers import Container
import time
import psutil
import subprocess
import docker
import docker.errors
import sys
from dataclasses import dataclass
from typing import Literal, cast, Final, Iterator
from scheduler_logger import SchedulerLogger, Job

CoreId = Literal[1, 2, 3]
NumThreads = Literal[1, 2, 3]

@dataclass
class CoreSets:
    r: set[CoreId]
    b: set[CoreId]
    bs: set[CoreId]

    def m_extra(self) -> set[CoreId]:
        return cast(set[CoreId], {1,2,3}) - self.r - self.b - self.bs

    def num(self) -> Literal[1,2,3]:
        return len(self.r) + len(self.b) + len(self.bs) # type: ignore

@dataclass
class JobInfo:
    image: str
    cmd: str
    threads: NumThreads

JOBS_INFO: Final[dict[Job, JobInfo]] = {
    Job.BARNES: JobInfo(image="anakli/cca:splash2x_barnes", cmd="./run -a run -S splash2x -p barnes -i native -n 2", threads=2),
    Job.RADIX: JobInfo(image="anakli/cca:splash2x_radix", cmd="./run -a run -S splash2x -p radix -i native -n 1", threads=1),
    Job.BLACKSCHOLES: JobInfo(image="anakli/cca:parsec_blackscholes", cmd="./run -a run -S parsec -p blackscholes -i native -n 3", threads=3),
    Job.CANNEAL: JobInfo(image="anakli/cca:parsec_canneal", cmd="./run -a run -S parsec -p canneal -i native -n 3", threads=3),
    Job.FREQMINE: JobInfo(image="anakli/cca:parsec_freqmine", cmd="./run -a run -S parsec -p freqmine -i native -n 3", threads=3),
    Job.STREAMCLUSTER: JobInfo(image="anakli/cca:parsec_streamcluster", cmd="./run -a run -S parsec -p streamcluster -i native -n 3", threads=3),
    Job.VIPS: JobInfo(image="anakli/cca:parsec_vips", cmd="./run -a run -S parsec -p vips -i native -n 3", threads=3)
}

PARSEC_JOBS: Final[list[Job]] = [Job.BLACKSCHOLES, Job.CANNEAL, Job.FREQMINE, Job.STREAMCLUSTER, Job.VIPS]

def _read_proc_stat() -> list[tuple[int,int]]:
    with open("/proc/stat") as f:
        return [(cols[3], sum(cols))
           for line in f
           if line.startswith("cpu") and line[3].isdigit()
           for cols in [list(map(int, line.split()[1:9]))]
        ]

class JobManager:
    logger: SchedulerLogger
    client: DockerClient
    ran_jobs: dict[Job, bool] # { job: <completed_else_running> }
    memc_pid: int
    memc_cores: set[CoreId]
    memc_cpu: float

    def __init__(self, logger: SchedulerLogger, client: DockerClient):
        self.logger = logger
        self.client = client
        self.ran_jobs = {}

        for c in self.client.containers.list(all=True, filters={"name": "cca_"}):
            try:
                c.remove(force=True)
            except Exception:
                pass
        
        for j, info in JOBS_INFO.items():
            try:
                self.client.images.get(info.image)
            except docker.errors.ImageNotFound:
                self.client.images.pull(info.image)

            self.client.containers.create(
                info.image,
                info.cmd,
                detach=True,
                name=f"cca_{j.value}"
            )

        pid = next((p.pid for p in psutil.process_iter(["pid", "name"]) if p.info["name"] == "memcached"), None)
        if pid is None:
            print("Error: Memcached process not found")
            sys.exit(1)

        self.memc_pid = pid
        self.memc_cores = set()
        logger.job_start(Job.MEMCACHED, ["0"], 3) # need to log this – see project description page 24
        self.ensure_memc({1,2})


    def clear_cache(self) -> None:
        self.get_container.cache_clear()

    @lru_cache(maxsize=16)
    def get_container(self, job: Job) -> Container | None:
        for i in range(5):
            try:
                return self.client.containers.get(f"cca_{job.value}")
            except docker.errors.NotFound:
                return None
            except docker.errors.APIError:
                print(f"Encountered race condition inside `docker` library – retrying {i}/5 times")
                time.sleep(0.05)
        return None

    def is_completed(self, job: Job):
        return self.ran_jobs.get(job, False)

    def ensure_memc(self, cs: set[CoreId]):
        if cs == self.memc_cores: return
        memc_cores_w0 = ["0", *map(str, cs)]
        subprocess.run(
            ["sudo", "taskset", "-a", "-cp", ",".join(memc_cores_w0), str(self.memc_pid)],
            check=True, capture_output=True,
        )
        self.memc_cores = set(cs)

        self.logger.update_cores(Job.MEMCACHED, memc_cores_w0)
        print(f"[MEMCACHED] cores updated to: {memc_cores_w0}")

    def ensure_cores(self, job: Job, cs: set[CoreId]) -> bool:
        if job not in self.ran_jobs:
            if len(cs) == 0: return True
            self.start_job(job, cs)
            return True
        # finshed long time ago
        if self.ran_jobs[job]: return len(cs) == 0

        # just finished
        container = self.get_container(job)
        if container is None or container.status == 'exited':
            self.ran_jobs[job] = True
            self.logger.job_end(job)
            print(f"[{job.value}] ended.")
            return len(cs) == 0

        # `job` is currently paused or running
        try:
            # case 1: we want to pause `job`
            if len(cs) == 0:
                if container.status != 'paused':
                    container.pause()
                    self.logger.job_pause(job)
                    print(f"[{job.value}] paused.")
                return True
            # case 2: we want `job` to run
            if container.status == 'paused':
                container.unpause()
                self.logger.job_unpause(job)
                print(f"[{job.value}] unpaused.")

            if self.cores(job) != cs:
                container.update(cpuset_cpus=",".join(map(str, cs)))
                self.logger.update_cores(job, list(map(str,cs)))
                print(f"[{job.value}] cores updated to: {list(cs)}")

        except docker.errors.APIError:
            pass
        return True

    def avail_cores(self, cores: Literal[1,2,3]) -> Literal[1,2,3]:
        return min(3, max(1, cores + self.delta_cores())) # type: ignore

    def delta_cores(self) -> int:
        memc_cores = 1 + len(self.memc_cores) 
        return(
            -2 if self.memc_cpu > 95.0 * memc_cores else
            -1 if self.memc_cpu > 85.0 * memc_cores else
            2 if memc_cores == 3 and self.memc_cpu < 80.0 else
            1 if memc_cores in {2,3} and self.memc_cpu < 80.0 * (memc_cores - 1) else
            0
        )
        
    def start_job(self, job: Job, cores: set[CoreId]) -> None:
        info = JOBS_INFO[job]
        core_str = ",".join(map(str, cores))
        self.ran_jobs[job] = False
        
        try:
            container = self.get_container(job)
            if container is None:
                raise Exception("Container not found")
            container.update(cpuset_cpus=core_str)
            container.start()
        except Exception as e:
            print(f"Error starting {job.value}: {e}")
            self.ran_jobs[job] = True
            return

        self.logger.job_start(job, [str(c) for c in cores], info.threads)
        print(f"[{job.value}] started on cores: {list(cores)} with {info.threads} threads.")

    def cores(self, job: Job) -> set[CoreId]:
        container = self.get_container(job)
        if container is None:
            return set()
        
        cpuset_str = cast(dict[str,str], container.attrs.get('HostConfig', {})).get('CpusetCpus')
        if not cpuset_str:
            return set()

        res = set()
        for part in cpuset_str.split(','):
            if '-' in part:
                start, end = map(int, part.split('-'))
                res.update(range(start, end + 1))
            else:
                res.add(int(part))
        return cast(set[CoreId], res)

    def sleep_and_measure_memc_util(self):
        before = _read_proc_stat()
        time.sleep(0.4)
        after = _read_proc_stat()
        diffs: Iterator[tuple[int,int]] = ((idle_a - idle_b, tot_a - tot_b) for ((idle_b, tot_b), (idle_a, tot_a)) in zip(before, after))
        cpu_util: list[float] = [(0.0 if total == 0 else 1.0 - idle / total) for (idle, total) in diffs]
        self.memc_cpu = (cpu_util[0] + sum(cpu_util[c] for c in self.memc_cores)) * 100.0
        monitor_msg = f"[monitor] {[f'{u:.0%}' for u in cpu_util]}  memcached={self.memc_cpu:.1f}%"
        print(monitor_msg)
        self.logger.custom_event(Job.SCHEDULER, monitor_msg)
        self.clear_cache()


class SplashPhase:
    jm: JobManager
    cs: CoreSets # wanted cores per job (realized with `sync`)

    def __init__(self):
        self.jm = JobManager(SchedulerLogger(), docker.from_env())
        self.cs = CoreSets({3}, set(), set())
        self.sync()

    def sync(self):
        self.jm.ensure_memc(self.cs.m_extra())
        self.jm.ensure_cores(Job.RADIX, self.cs.r)
        self.jm.ensure_cores(Job.BARNES, self.cs.b)
        self.jm.ensure_cores(Job.BLACKSCHOLES, self.cs.bs)

    def reallocate(self, nr: int, nb: int, nbs: int) -> None:
        cs = self.cs
        m = cs.m_extra()
        nm = 3 - nr - nb - nbs
        surplus: list[CoreId] = []
        while len(cs.r) > nr: surplus.append(cs.r.pop())
        while len(cs.b) > nb: surplus.append(cs.b.pop())
        while len(cs.bs) > nbs: surplus.append(cs.bs.pop())
        while len(m) > nm: surplus.append(m.pop())
        while len(cs.r) < nr: cs.r.add(surplus.pop())
        while len(cs.b) < nb: cs.b.add(surplus.pop())
        while len(cs.bs) < nbs: cs.bs.add(surplus.pop())

    def avail_cores(self) -> Literal[1,2,3]:
        return self.jm.avail_cores(self.cs.num())

@dataclass
class ParsecPhase:
    jm: JobManager
    cores: set[CoreId] # current job's cores (wanted cores is always {1,2,3} - self.jm.memc_cores)
    ix: int

    def __init__(self, phase1: SplashPhase):
        self.jm = phase1.jm
        self.cores = phase1.cs.bs
        self.ix = 1 if self.jm.is_completed(Job.BLACKSCHOLES) else 0

    def reallocate(self, n: int) -> None:
        cores: set[CoreId] = self.cores
        m_extra = cast(set[CoreId], {1,2,3}) - cores
        while len(cores) < n: cores.add(m_extra.pop())
        while len(cores) > n: cores.pop()

    def sync(self):
        self.jm.ensure_memc(cast(set[CoreId], {1, 2, 3}) - self.cores)
        self.jm.ensure_cores(PARSEC_JOBS[self.ix], self.cores)

    def next_job(self):
        self.ix += 1
        self.cores = set()


def run_controller(log_dir: str = ".") -> None:
    os.makedirs(log_dir, exist_ok=True)
    os.chdir(log_dir)

    print("Scheduler started.")
    phase1 = SplashPhase()
    phase1.jm.sleep_and_measure_memc_util()
    try:
        while not phase1.jm.is_completed(Job.BARNES) and not phase1.jm.is_completed(Job.RADIX):
            match phase1.avail_cores():
                case 3: phase1.reallocate(1, 2, 0)
                case 2: phase1.reallocate(0, 2, 0)
                case 1: phase1.reallocate(1, 0, 0)
            phase1.sync()
            phase1.jm.sleep_and_measure_memc_util()
            phase1.sync() # marks completed jobs as completed

        while not phase1.jm.is_completed(Job.BARNES):
            match phase1.avail_cores():
                case 3: phase1.reallocate(0, 2, 1)
                case 2: phase1.reallocate(0, 2, 0)
                case 1: phase1.reallocate(0, 0, 1)
            phase1.sync()
            phase1.jm.sleep_and_measure_memc_util()
            phase1.sync()

        while not phase1.jm.is_completed(Job.RADIX):
            match phase1.avail_cores():
                case 3: phase1.reallocate(1, 0, 2)
                case 2: phase1.reallocate(1, 0, 1)
                case 1: phase1.reallocate(1, 0, 0)
            phase1.sync()
            phase1.jm.sleep_and_measure_memc_util()
            phase1.sync()

        phase2 = ParsecPhase(phase1)

        while phase2.ix < len(PARSEC_JOBS):
            if phase2.jm.is_completed(PARSEC_JOBS[phase2.ix]):
                phase2.next_job()
                continue
            # can't use phase2.cores, because switching jobs sets it (the current job's cores) to empty `set()`
            free_cores = cast(Literal[1,2,3], 3 - len(phase2.jm.memc_cores))
            phase2.reallocate(phase2.jm.avail_cores(free_cores))
            phase2.sync()
            memc_cpu = phase2.jm.sleep_and_measure_memc_util()
            phase2.sync()

    except KeyboardInterrupt:
        print("\nScheduler interrupted")
    finally:
        try:
            subprocess.run(
                ["sudo", "taskset", "-a", "-cp", "0,1,2,3", str(phase1.jm.memc_pid)],
                check=False, capture_output=True
            )
            phase1.jm.logger.update_cores(Job.MEMCACHED, ["0","1","2","3"])
            print("[MEMCACHED] cores updated to: ['0', '1', '2', '3']")
        except Exception as e:
            print(f"Error returning cores back to memcached: {e}")
        phase1.jm.logger.end()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-dir", default=".")
    args = parser.parse_args()
    run_controller(log_dir=args.log_dir)
