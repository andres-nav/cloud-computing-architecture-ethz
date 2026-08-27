import sys
import multiprocessing

try:
    multiprocessing.set_start_method("spawn")
except RuntimeError:
    pass

import importlib.util
import subprocess
import time
import threading
import os
from dataclasses import dataclass
from typing import Final
from datetime import datetime
from enum import Enum
from pathlib import Path
import traceback
import yaml
import signal

from kr8s.objects import Node, Pod, Job, Service
from kr8s._types import SpecType

try:
    from openevolve.evaluation_result import EvaluationResult
except ImportError:
    @dataclass
    class EvaluationResult:
        metrics: dict[str, float]
        artifacts: dict[str, str]


def _install_reasoning_patches() -> None:
    import re as _re
    import asyncio as _asyncio

    try:
        from openevolve.llm import openai as _oai_mod

        _orig_call_api = _oai_mod.OpenAILLM._call_api

        async def _patched_call_api(self: "_oai_mod.OpenAILLM", params: dict[str, str]) -> str:
            if self.client is None:
                raise RuntimeError("OpenAI client is not initialized")
            client = self.client
            loop = _asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: client.chat.completions.create(**params)  # type: ignore[arg-type]
            )
            msg = response.choices[0].message
            content = msg.content or ""
            reasoning = getattr(msg, "reasoning_content", None) or ""
            if reasoning:
                content = f"<think>\n{reasoning}\n</think>\n\n{content}"
            return content

        _oai_mod.OpenAILLM._call_api = _patched_call_api  # type: ignore[assignment]
    except Exception as e:
        print(f"[evaluator] Warning: failed to patch _call_api: {e}", file=sys.stderr)

    try:
        from openevolve.utils import code_utils as _cu_mod

        _orig_parse = _cu_mod.parse_full_rewrite

        def _patched_parse(llm_response: str, language: str = "python") -> str | None:
            think_blocks: list[str] = _re.findall(
                r"<think>(.*?)</think>", llm_response, _re.DOTALL,
            )
            reasoning = "\n\n".join(b.strip() for b in think_blocks if b.strip())

            code = _orig_parse(llm_response, language)
            if code is None:
                return None

            if reasoning:
                code = _re.sub(
                    r'^_REASONING\s*=\s*r?""".*?"""\s*\n*',
                    '', code, count=1, flags=_re.DOTALL | _re.MULTILINE,
                )
                escaped = reasoning.replace('\\', '\\\\').replace('"""', '\\"\\"\\"')
                code = f'_REASONING = r"""\n{escaped}\n"""\n\n{code}'

            return code

        _cu_mod.parse_full_rewrite = _patched_parse  # type: ignore[assignment]
        try:
            from openevolve import utils as _utils_init
            _utils_init.parse_full_rewrite = _patched_parse  # type: ignore[assignment]
        except Exception:
            pass
    except Exception as e:
        print(f"[evaluator] Warning: failed to patch parse_full_rewrite: {e}", file=sys.stderr)


_install_reasoning_patches()


def _worker_sigint_handler(signum: int, frame: object) -> None:
    for p in getattr(sys.modules[__name__], '_bg_procs', []):
        try:
            p.kill()
        except Exception:
            pass
    os._exit(0)

signal.signal(signal.SIGINT, _worker_sigint_handler)

TIMEOUT_JOBS: Final[int] = 900
SLO_THRESHOLD_US: Final[float] = 1000.0
MAX_MAKESPAN: Final[float] = 600.0
MCPERF_SETTLE: Final[int] = 15
SSH_OPTS: Final[list[str]] = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null"]
MCPERF_BIN: Final[str] = "./memcache-perf-dynamic/mcperf"

RESULTS_DIR: Final[Path] = Path(os.environ.get("RUN_DIR", str(Path(__file__).parent / "results"))) / "measurements"

TIME_FMT: Final[str] = "%Y-%m-%dT%H:%M:%SZ"


class JobEnum(Enum):
    BARNES = "barnes"
    BLACKSCHOLES = "blackscholes"
    CANNEAL = "canneal"
    FREQMINE = "freqmine"
    RADIX = "radix"
    STREAMCLUSTER = "streamcluster"
    VIPS = "vips"


IMG_MAP: Final[dict[str, str]] = {
    "barnes": "splash2x_barnes",
    "blackscholes": "parsec_blackscholes",
    "canneal": "parsec_canneal",
    "freqmine": "parsec_freqmine",
    "radix": "splash2x_radix",
    "streamcluster": "parsec_streamcluster",
    "vips": "parsec_vips",
}


@dataclass
class Metrics:
    success: bool
    makespan: float
    p95: float
    error: str
    times_txt: str
    mcperf_txt: str


@dataclass
class McperfIPs:
    measure_ext: str
    agent_a_ext: str
    agent_b_ext: str
    agent_a_int: str
    agent_b_int: str


_bg_procs: list[subprocess.Popen[str]] = []


def _ssh(host: str, cmd: str) -> str:
    result = subprocess.run(
        ["ssh", *SSH_OPTS, f"ubuntu@{host}", cmd],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"SSH error ({host}): {result.stderr.strip()}", file=sys.stderr)
    return result.stdout


def _ssh_bg(host: str, cmd: str) -> subprocess.Popen[str]:
    p = subprocess.Popen(
        ["ssh", *SSH_OPTS, f"ubuntu@{host}", cmd],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, text=True,
    )
    _bg_procs.append(p)
    return p


def _get_node(nodetype: str) -> Node | None:
    for item in Node.list(label_selector=f"cca-project-nodetype={nodetype}"):
        if isinstance(item, Node):
            return item
    return None


def get_node_ip(nodetype: str, internal: bool = True) -> str | None:
    node = _get_node(nodetype)
    if node is None:
        return None
    addr_type = "InternalIP" if internal else "ExternalIP"
    addresses: list[dict[str, str]] = node.raw.get("status", {}).get("addresses", [])
    for addr in addresses:
        if addr.get("type") == addr_type:
            return addr["address"]
    return None


def resolve_mcperf_ips() -> McperfIPs | None:
    measure = get_node_ip("client-measure", internal=False)
    agent_a_ext = get_node_ip("client-agent-a", internal=False)
    agent_b_ext = get_node_ip("client-agent-b", internal=False)
    agent_a_int = get_node_ip("client-agent-a", internal=True)
    agent_b_int = get_node_ip("client-agent-b", internal=True)
    if not (measure and agent_a_ext and agent_b_ext and agent_a_int and agent_b_int):
        return None
    return McperfIPs(
        measure_ext=measure,
        agent_a_ext=agent_a_ext,
        agent_b_ext=agent_b_ext,
        agent_a_int=agent_a_int,
        agent_b_int=agent_b_int,
    )


def cleanup_cluster() -> None:
    print("[evaluator] Cleaning cluster...", file=sys.stderr)

    for p in _bg_procs:
        try:
            p.kill()
            p.wait(timeout=1)
        except Exception:
            pass
    _bg_procs.clear()

    for cmd in [
        ["kubectl", "delete", "jobs", "--all", "--ignore-not-found"],
        ["kubectl", "delete", "pods", "--all", "--ignore-not-found"],
        ["kubectl", "delete", "service", "some-memcached-11211", "--ignore-not-found"],
    ]:
        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for nodetype in ["client-measure", "client-agent-a", "client-agent-b"]:
        ip = get_node_ip(nodetype, internal=False)
        if ip:
            _ssh(ip, "pkill -f mcperf || true")

    for _ in range(30):
        has_pods = False
        for item in Pod.list(namespace="default"):
            has_pods = True
            break
        if not has_pods:
            break
        time.sleep(2)


def deploy_memcached() -> str | None:
    print("[evaluator] Deploying memcached...", file=sys.stderr)

    pod = Pod({
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": "some-memcached", "labels": {"name": "some-memcached"}},
        "spec": {
            "containers": [{
                "image": "anakli/memcached:t1",
                "name": "memcached",
                "command": ["/bin/sh"],
                "args": ["-c", "taskset -c 0 ./memcached -t 1 -u memcache"],
            }],
            "nodeSelector": {"cca-project-nodetype": "node-b-4core"},
        },
    })
    pod.create()

    svc = Service({
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": "some-memcached-11211"},
        "spec": {
            "type": "LoadBalancer",
            "selector": {"name": "some-memcached"},
            "ports": [{"port": 11211, "targetPort": 11211, "protocol": "TCP"}],
        },
    })
    svc.create()

    try:
        pod.wait("condition=Ready", timeout=120)
    except TimeoutError:
        print("[evaluator] memcached pod did not become Ready", file=sys.stderr)
        return None

    pod.refresh()
    pod_ip: str | None = pod.raw.get("status", {}).get("podIP")
    return pod_ip


def start_mcperf(memcached_ip: str, ips: McperfIPs) -> str | None:
    _ssh(ips.agent_a_ext, "pkill -f mcperf || true")
    _ssh(ips.agent_b_ext, "pkill -f mcperf || true")

    _ssh_bg(ips.agent_a_ext, f"nohup {MCPERF_BIN} -T 2 -A > /dev/null 2>&1 &")
    _ssh_bg(ips.agent_b_ext, f"nohup {MCPERF_BIN} -T 4 -A > /dev/null 2>&1 &")

    _ssh(ips.measure_ext, f"{MCPERF_BIN} -s {memcached_ip} --loadonly")
    _ssh(ips.measure_ext, "> /home/ubuntu/mcperf.txt")

    mcperf_cmd = (
        f"while true; do {MCPERF_BIN} -s {memcached_ip} "
        f"-a {ips.agent_a_int} -a {ips.agent_b_int} "
        f"--noload -T 6 -C 4 -D 4 -Q 1000 -c 4 -t 10 "
        f"--scan 30000:30500:5 >> /home/ubuntu/mcperf.txt 2>&1; done"
    )
    _ssh_bg(ips.measure_ext, mcperf_cmd)
    time.sleep(MCPERF_SETTLE)
    return None



def build_job_spec(name: str, node_kind: str, cores: set[int], threads: int) -> SpecType:
    img = IMG_MAP[name]
    suite = "splash2x" if img.startswith("splash2x") else "parsec"
    nodetype = "node-a-8core" if node_kind == "A" else "node-b-4core"
    cores_str = ",".join(map(str, sorted(cores)))

    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": f"parsec-{name}",
            "labels": {"name": f"parsec-{name}"},
        },
        "spec": {
            "template": {
                "spec": {
                    "containers": [{
                        "image": f"anakli/cca:{img}",
                        "name": f"parsec-{name}",
                        "command": ["/bin/sh"],
                        "args": ["-c", f"taskset -c {cores_str} ./run -a run -S {suite} -p {name} -i native -n {threads}"],
                    }],
                    "restartPolicy": "Never",
                    "nodeSelector": {"cca-project-nodetype": nodetype},
                },
            },
        },
    }


def wait_k8s_job(name: str, timeout: int) -> bool:
    try:
        job = Job.get(f"parsec-{name}", namespace="default")
        assert isinstance(job, Job)
        job.wait(["condition=Complete", "condition=Failed"], timeout=timeout)
        job.refresh()

        conditions: list[dict[str, str]] = job.raw.get("status", {}).get("conditions", [])
        for c in conditions:
            if c.get("type") == "Complete" and c.get("status") == "True":
                return True
            if c.get("type") == "Failed" and c.get("status") == "True":
                print(f"[evaluator] Job {name} failed: {c.get('reason', '?')}", file=sys.stderr)
                return False
        return False
    except TimeoutError:
        print(f"[evaluator] Job {name} timed out after {timeout}s", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[evaluator] Error waiting for {name}: {e}", file=sys.stderr)
        return False


def job_worker(
    name: str,
    job_spec: SpecType,
    after: str | None,
    events: dict[str, threading.Event],
) -> None:
    if after:
        events[after].wait()

    try:
        Job(job_spec).create()
        if wait_k8s_job(name, TIMEOUT_JOBS):
            print(f"[evaluator] {name} completed", file=sys.stderr)
            events[name].set()
        else:
            print(f"[evaluator] {name} did not succeed", file=sys.stderr)
    except Exception as e:
        print(f"[evaluator] Error creating {name}: {e}", file=sys.stderr)



def _parse_p95(mcperf_txt: str) -> float | None:
    max_p95: float | None = None
    for line in mcperf_txt.splitlines():
        if line.startswith("read"):
            parts = line.split()
            try:
                p95 = float(parts[12])
                max_p95 = p95 if max_p95 is None else max(max_p95, p95)
            except (ValueError, IndexError):
                continue
    return max_p95


def collect_metrics() -> Metrics:
    # Fetch mcperf output
    measure = get_node_ip("client-measure", internal=False)
    mcperf_txt = _ssh(measure, "cat /home/ubuntu/mcperf.txt") if measure else ""

    starts: list[datetime] = []
    ends: list[datetime] = []
    lines: list[str] = []

    for item in Pod.list(namespace="default"):
        if not isinstance(item, Pod):
            continue
        container_statuses: list[dict[str, str | dict[str, dict[str, str]]]] = item.raw.get("status", {}).get("containerStatuses", [])
        if not container_statuses:
            continue
        cs = container_statuses[0]
        name = str(cs.get("name", ""))
        if name == "memcached":
            continue

        state = cs.get("state")
        if not isinstance(state, dict):
            continue
        term = state.get("terminated")
        if not isinstance(term, dict):
            continue
        started = term.get("startedAt")
        finished = term.get("finishedAt")
        if not isinstance(started, str) or not isinstance(finished, str):
            continue

        t0 = datetime.strptime(started, TIME_FMT)
        t1 = datetime.strptime(finished, TIME_FMT)
        starts.append(t0)
        ends.append(t1)
        lines.append(f"{name}: {t1 - t0}")

    if len(starts) < 7:
        return Metrics(
            success=False, error=f"Only {len(starts)}/7 jobs completed",
            makespan=0.0, p95=0.0, times_txt="", mcperf_txt=mcperf_txt,
        )

    makespan = (max(ends) - min(starts)).total_seconds()
    lines.append(f"Total: {makespan}")
    times_txt = "\n".join(lines) + "\n"

    p95 = _parse_p95(mcperf_txt)
    if p95 is None:
        return Metrics(
            success=False, error="No latency data in mcperf output",
            makespan=makespan, p95=0.0, times_txt=times_txt, mcperf_txt=mcperf_txt,
        )

    return Metrics(
        success=True, error="",
        makespan=makespan, p95=p95, times_txt=times_txt, mcperf_txt=mcperf_txt,
    )



def save_artifacts(yaml_docs: list[SpecType], metrics: Metrics) -> None:
    try:
        d = RESULTS_DIR / datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
        d.mkdir(parents=True, exist_ok=True)
        (d / "times.txt").write_text(metrics.times_txt)
        (d / "mcperf.txt").write_text(metrics.mcperf_txt)
        (d / "policy.yaml").write_text(yaml.dump_all(yaml_docs))
        print(f"[evaluator] Results saved to {d}", file=sys.stderr)
    except Exception as e:
        print(f"[evaluator] Error saving artifacts: {e}", file=sys.stderr)



def _fail(msg: str) -> EvaluationResult:
    print(f"[evaluator] FAIL: {msg}", file=sys.stderr)
    return EvaluationResult(
        metrics={"combined_score": 0.0, "makespan_score": 0.0, "slo_score": 0.0},
        artifacts={"error": msg},
    )


def _sanitize_program(program_path: str) -> None:
    import re

    with open(program_path, "r") as f:
        content = f.read()

    match = re.search(r"```(?:python)?\s*\n(.*?)\n\s*```", content, re.DOTALL | re.IGNORECASE)
    if match:
        with open(program_path, "w") as f:
            f.write(match.group(1))


def evaluate(program_path: str) -> EvaluationResult:
    try:
        _sanitize_program(program_path)
    except Exception as e:
        print(f"[evaluator] Warning: sanitization failed: {e}", file=sys.stderr)

    spec = importlib.util.spec_from_file_location("evolved_policy", program_path)
    if not spec or not spec.loader:
        return _fail(f"Cannot load {program_path}")

    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        policy = module.get_policy()

        for j in JobEnum:
            jp = getattr(policy, j.value)
            if jp.node.kind == "B" and 0 in jp.node.cores:
                return _fail(f"Job {j.value} uses node-b core 0 (reserved for memcached)")

        cleanup_cluster()

        mem_ip = deploy_memcached()
        if not mem_ip:
            return _fail("Failed to deploy memcached")
        print(f"[evaluator] memcached pod IP: {mem_ip}", file=sys.stderr)

        ips = resolve_mcperf_ips()
        if ips is None:
            return _fail("Could not resolve mcperf node IPs")

        err = start_mcperf(mem_ip, ips)
        if err:
            return _fail(err)
        print("[evaluator] mcperf running. Launching batch jobs...", file=sys.stderr)

        events: dict[str, threading.Event] = {j.value: threading.Event() for j in JobEnum}
        yaml_docs: list[SpecType] = []
        threads: list[threading.Thread] = []

        for j in JobEnum:
            jp = getattr(policy, j.value)
            job_spec = build_job_spec(j.value, jp.node.kind, jp.node.cores, jp.threads)
            yaml_docs.append(job_spec)
            after: str | None = jp.after.value if jp.after else None

            t = threading.Thread(target=job_worker, args=(j.value, job_spec, after, events))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        print("[evaluator] All jobs done. Collecting metrics...", file=sys.stderr)

        metrics = collect_metrics()
        save_artifacts(yaml_docs, metrics)

        if not metrics.success:
            return _fail(metrics.error)

        makespan = metrics.makespan
        p95 = metrics.p95
        print(f"[evaluator] makespan={makespan:.0f}s  p95={p95:.1f}us", file=sys.stderr)

        makespan_score = max(0.0, 1.0 - makespan / MAX_MAKESPAN)
        slo_score = 1.0 if p95 <= SLO_THRESHOLD_US else 0.1
        combined = makespan_score * slo_score

        return EvaluationResult(
            metrics={
                "combined_score": combined,
                "makespan_score": makespan_score,
                "slo_score": slo_score,
                "makespan_seconds": makespan,
                "p95_us": p95,
            },
            artifacts={
                "makespan": f"{makespan:.0f}s",
                "p95": f"{p95:.1f}us",
                "times": metrics.times_txt,
            },
        )

    except Exception as e:
        return _fail(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
    finally:
        cleanup_cluster()
