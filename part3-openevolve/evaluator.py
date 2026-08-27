import importlib.util
import json
import os
import sys
import signal
import subprocess
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path

def _worker_sigint_handler(signum, frame):
    for p in getattr(sys.modules[__name__], '_bg_procs', []):
        try:
            p.kill()
        except:
            pass
    os._exit(0)

signal.signal(signal.SIGINT, _worker_sigint_handler)

from openevolve.evaluation_result import EvaluationResult

JOBS = {
    "blackscholes":  {"image": "anakli/cca:parsec_blackscholes",  "suite": "parsec"},
    "canneal":       {"image": "anakli/cca:parsec_canneal",       "suite": "parsec"},
    "freqmine":      {"image": "anakli/cca:parsec_freqmine",      "suite": "parsec"},
    "vips":          {"image": "anakli/cca:parsec_vips",          "suite": "parsec"},
    "streamcluster": {"image": "anakli/cca:parsec_streamcluster", "suite": "parsec"},
    "radix":         {"image": "anakli/cca:splash2x_radix",       "suite": "splash2x"},
    "barnes":        {"image": "anakli/cca:splash2x_barnes",      "suite": "splash2x"},
}
VALID_NODES = {"node-a-8core", "node-b-4core"}
TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"
MAX_MAKESPAN = 600.0
MCPERF_SETTLE = 15

SSH_KEY = os.path.expanduser(os.environ.get("SSH_KEY", "~/.ssh/id_ecdsa"))
SSH_OPTS = ["-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null"]
RESULTS_DIR = Path(os.environ.get("RUN_DIR", Path(__file__).parent / "results")) / "measurements"
LAUNCHER = str(Path(__file__).parent.parent / "part3" / "launcher.py")
MCPERF = "/home/ubuntu/memcache-perf-dynamic/mcperf"

_MEMCACHED_TEMPLATE = """\
apiVersion: v1
kind: Pod
metadata:
  name: some-memcached
  labels:
    name: some-memcached
spec:
  containers:
    - image: anakli/memcached:t1
      name: memcached
      imagePullPolicy: Always
      command: ["/bin/sh"]
      args: ["-c", "taskset -c {cores} ./memcached -t {threads} -u memcache"]
  nodeSelector:
    cca-project-nodetype: "{node}"
"""

_JOB_TEMPLATE = """\
apiVersion: batch/v1
kind: Job
metadata:
  name: parsec-{name}
  labels:
    name: parsec-{name}
spec:
  template:
    spec:
      containers:
      - image: {image}
        name: parsec-{name}
        imagePullPolicy: Always
        command: ["/bin/sh"]
        args: ["-c", "taskset -c {cores} ./run -a run -S {suite} -p {name} -i native -n {threads}"]
      restartPolicy: Never
      nodeSelector:
        cca-project-nodetype: "{node}"
"""


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _ssh(host, cmd):
    return _run(["ssh"] + SSH_OPTS + [f"ubuntu@{host}", cmd])


_bg_procs = []

def _ssh_bg(host, cmd):
    """Run command on remote host in background."""
    p = subprocess.Popen(
        ["ssh"] + SSH_OPTS + [f"ubuntu@{host}", cmd],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    _bg_procs.append(p)


def _node_ip(nodetype, kind):
    rc, out, _ = _run([
        "kubectl", "get", "nodes",
        f"--selector=cca-project-nodetype={nodetype}",
        "-o", f'jsonpath={{.items[0].status.addresses[?(@.type=="{kind}")].address}}',
    ])
    return out.strip() if rc == 0 else None


def _parse_cores(spec):
    cores = set()
    for part in spec.split(","):
        if "-" in part:
            lo, hi = part.split("-", 1)
            cores.update(range(int(lo), int(hi) + 1))
        else:
            cores.add(int(part))
    return cores


def _check_placement(name, cfg):
    if cfg["node"] not in VALID_NODES:
        return f"{name}: invalid node '{cfg['node']}'"
    if not isinstance(cfg["threads"], int) or cfg["threads"] < 1:
        return f"{name}: threads must be positive int"
    return None


def _validate(memcached, schedule, dependencies):
    err = _check_placement("memcached", memcached)
    if err:
        return err
    if set(schedule.keys()) != set(JOBS.keys()):
        return f"Expected jobs {set(JOBS.keys())}, got {set(schedule.keys())}"
    mc_cores = _parse_cores(memcached["cores"])
    for name, cfg in schedule.items():
        err = _check_placement(name, cfg)
        if err:
            return err
        if cfg["node"] == memcached["node"] and _parse_cores(cfg["cores"]) & mc_cores:
            return f"{name}: cores overlap with memcached on {cfg['node']}"
    for job, dep in dependencies.items():
        if job not in JOBS or dep not in JOBS:
            return f"Unknown job in dependency: {job} -> {dep}"
    return None


def _generate_yaml(memcached, schedule, dependencies):
    parts = [_MEMCACHED_TEMPLATE.format(**memcached)]
    for name in sorted(schedule, key=lambda n: n in dependencies):
        cfg = schedule[name]
        block = _JOB_TEMPLATE.format(
            name=name, image=JOBS[name]["image"], suite=JOBS[name]["suite"],
            node=cfg["node"], cores=cfg["cores"], threads=cfg["threads"],
        )
        if name in dependencies:
            block = f"# AFTER parsec-{dependencies[name]}\n{block}"
        parts.append(block)
    return "---\n".join(parts)


# --- Cluster operations ---

def _cleanup():
    for p in getattr(sys.modules[__name__], '_bg_procs', []):
        try:
            p.kill()
            p.wait(timeout=1)
        except Exception:
            pass
    getattr(sys.modules[__name__], '_bg_procs', []).clear()

    _run(["kubectl", "delete", "jobs", "--all", "--ignore-not-found"])
    _run(["kubectl", "delete", "pods", "--all", "--ignore-not-found"])
    _run(["kubectl", "delete", "service", "some-memcached-11211", "--ignore-not-found"])
    _run(["kubectl", "wait", "--for=delete", "pod", "--all"])
    for node in ["client-measure", "client-agent-a", "client-agent-b"]:
        ip = _node_ip(node, "ExternalIP")
        if ip:
            _ssh(ip, "pkill -f mcperf || true")


def _deploy_memcached(memcached):
    """Returns (pod_ip, error)."""
    print(f"[evaluator] deploying memcached: {memcached}")
    proc = subprocess.run(["kubectl", "create", "-f", "-"],
                          input=_MEMCACHED_TEMPLATE.format(**memcached),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return None, f"Failed to create memcached: {proc.stderr}"
    print("[evaluator] memcached pod created, exposing service...")
    _run(["kubectl", "expose", "pod", "some-memcached",
          "--name", "some-memcached-11211",
          "--type", "LoadBalancer", "--port", "11211", "--protocol", "TCP"])
    print("[evaluator] waiting for pod ready...")
    rc, _, _ = _run(["kubectl", "wait", "--for=condition=Ready",
                      "pod/some-memcached"])
    if rc != 0:
        return None, "Memcached pod not ready"
    rc, ip, _ = _run(["kubectl", "get", "pod", "some-memcached",
                       "-o", "jsonpath={.status.podIP}"])
    if rc == 0 and ip.strip():
        return ip.strip(), None
    return None, "Could not get memcached pod IP"


def _start_mcperf(memcached_ip):
    """Returns error string or None."""
    print(f"[evaluator] starting mcperf, memcached_ip={memcached_ip}")
    measure = _node_ip("client-measure", "ExternalIP")
    agent_a = _node_ip("client-agent-a", "ExternalIP")
    agent_b = _node_ip("client-agent-b", "ExternalIP")
    agent_a_int = _node_ip("client-agent-a", "InternalIP")
    agent_b_int = _node_ip("client-agent-b", "InternalIP")
    if not all([measure, agent_a, agent_b, agent_a_int, agent_b_int]):
        return "Could not resolve mcperf node IPs"
    print(f"[evaluator] IPs: measure={measure} agent_a={agent_a} agent_b={agent_b}")

    print("[evaluator] starting agents...")
    _ssh_bg(agent_a, f"{MCPERF} -T 2 -A > /dev/null 2>&1")
    _ssh_bg(agent_b, f"{MCPERF} -T 4 -A > /dev/null 2>&1")

    print("[evaluator] loading memcached data...")
    rc, _, err = _ssh(measure, f"{MCPERF} -s {memcached_ip} --loadonly")
    if rc != 0:
        return f"mcperf loadonly failed: {err}"
    print("[evaluator] loadonly done, starting measurement...")

    _ssh(measure, "> /home/ubuntu/mcperf.txt")
    _ssh_bg(measure, f"while true; do {MCPERF} -s {memcached_ip} "
            f"-a {agent_a_int} -a {agent_b_int} "
            f"--noload -T 6 -C 4 -D 4 -Q 1000 -c 4 -t 10 "
            f"--scan 30000:30500:5 "
            f">> /home/ubuntu/mcperf.txt 2>&1; done")
    time.sleep(MCPERF_SETTLE)
    return None


# --- Measurement ---

def _parse_makespan(pods_json):
    starts, ends, lines = [], [], []
    for item in json.loads(pods_json)["items"]:
        name = item["status"]["containerStatuses"][0]["name"]
        if not name.startswith("parsec-"):
            continue
        term = item["status"]["containerStatuses"][0]["state"].get("terminated")
        if not term:
            raise ValueError(f"Job {name} has not terminated")
        start = datetime.strptime(term["startedAt"], TIME_FMT)
        end = datetime.strptime(term["finishedAt"], TIME_FMT)
        lines.append(f"{name}: {end - start}")
        starts.append(start)
        ends.append(end)
    if len(starts) != 7:
        raise ValueError(f"Expected 7 completed jobs, found {len(starts)}")
    total = max(ends) - min(starts)
    lines.append(f"Total: {total}")
    return total.total_seconds(), "\n".join(lines) + "\n"


def _get_mcperf_p95():
    measure = _node_ip("client-measure", "ExternalIP")
    if not measure:
        return None, ""
    rc, out, _ = _ssh(measure, "tail -50 /home/ubuntu/mcperf.txt")
    if rc != 0 or not out.strip():
        return None, ""
    p95s = [float(line.split()[12])
            for line in out.strip().split("\n")
            if line.startswith("read") and len(line.split()) >= 13]
    return (max(p95s) if p95s else None), out


def _save_results(pods_json, times_txt, mcperf_txt, yaml_str):
    d = RESULTS_DIR / datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
    d.mkdir(parents=True, exist_ok=True)
    for name, content in [("pods.json", pods_json), ("times.txt", times_txt),
                           ("mcperf.txt", mcperf_txt), ("policy.yaml", yaml_str)]:
        (d / name).write_text(content)
    print(f"Results saved to {d}")


# --- Main entry point ---

def _fail(msg):
    return EvaluationResult(
        metrics={"combined_score": 0.0, "makespan_score": 0.0, "slo_score": 0.0},
        artifacts={"error": msg},
    )


def evaluate(program_path: str) -> EvaluationResult:
    yaml_path = None
    try:
        spec = importlib.util.spec_from_file_location("evolved", program_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        memcached, schedule, deps = mod.generate_schedule()
        if not all(isinstance(x, dict) for x in [memcached, schedule, deps]):
            return _fail("generate_schedule() must return (dict, dict, dict)")
        err = _validate(memcached, schedule, deps)
        if err:
            return _fail(f"Validation: {err}")

        yaml_str = _generate_yaml(memcached, schedule, deps)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_str)
            yaml_path = f.name

        _cleanup()
        print("[evaluator] cleanup done")

        mc_ip, err = _deploy_memcached(memcached)
        if err:
            return _fail(err)
        print(f"[evaluator] memcached deployed, pod IP: {mc_ip}")

        err = _start_mcperf(mc_ip)
        if err:
            return _fail(err)
        print("[evaluator] mcperf started")

        print("[evaluator] launching batch jobs...")
        rc, out, stderr = _run(["python3", LAUNCHER, yaml_path])
        if rc != 0:
            return _fail(f"Launcher failed: {stderr}\n{out}")
        print("[evaluator] batch jobs completed")

        rc, pods_json, _ = _run(["kubectl", "get", "pods", "-o", "json"])
        if rc != 0:
            return _fail("Failed to get pods")

        makespan, times_txt = _parse_makespan(pods_json)
        p95, mcperf_txt = _get_mcperf_p95()
        _save_results(pods_json, times_txt, mcperf_txt, yaml_str)
        print(f"[evaluator] makespan={makespan:.0f}s p95={p95}us")

        makespan_score = max(0.0, 1.0 - makespan / MAX_MAKESPAN)
        slo_score = 1.0 if p95 is not None and p95 <= 1000.0 else (
            0.5 if p95 is None else 0.1)
        combined = makespan_score * slo_score

        return EvaluationResult(
            metrics={
                "combined_score": combined,
                "makespan_score": makespan_score,
                "slo_score": slo_score,
                "makespan_seconds": makespan,
                "p95_us": p95 if p95 is not None else -1.0,
            },
            artifacts={
                "makespan": f"{makespan:.0f}s",
                "p95": f"{p95:.1f}us" if p95 else "unknown",
                "times": times_txt,
                "schedule": json.dumps(schedule, indent=2),
                "memcached": json.dumps(memcached),
                "dependencies": json.dumps(deps) if deps else "none",
            },
        )

    except Exception as e:
        return _fail(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
    finally:
        _cleanup()
        if yaml_path:
            try:
                os.unlink(yaml_path)
            except OSError:
                pass
