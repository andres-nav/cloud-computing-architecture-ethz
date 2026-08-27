#!/usr/bin/env python3
"""Launch batch jobs from a policy YAML with dependency support.

Each job can declare a dependency with a comment after its --- separator:
    ---
    # AFTER parsec-blackscholes
    apiVersion: batch/v1
    ...

Jobs without AFTER are launched immediately. Jobs with AFTER wait for
the named job to complete before launching.

Usage: python3 launcher.py policies/andres-v1.yaml [--timeout 900]
"""

import yaml
import sys
import argparse
import re
import json
import threading
import sys
from kubernetes import client, config, watch, utils

config.load_kube_config()

def parse_policy(path):
    """Parse policy YAML into memcached block and job entries with dependencies."""
    with open(path) as f:
        content = f.read()

    parts = re.split(r'\n---\n', content)
    memcached = parts[0]
    jobs = []

    for part in parts[1:]:
        part = part.strip()
        if not part or (part.startswith('#') and 'apiVersion' not in part):
            continue

        name_match = re.search(r'name: (parsec-\S+)', part)
        if not name_match:
            continue

        after = None
        for line in part.split('\n'):
            if line.strip().startswith('apiVersion'):
                break
            m = re.match(r'#\s*AFTER\s+(\S+)', line.strip())
            if m:
                after = m.group(1)

        jobs.append({'name': name_match.group(1), 'after': after, 'yaml': part})

    return memcached, jobs


def kubectl_create(yaml_str):
    k8s_client = client.ApiClient()
    try:
        for doc in yaml.safe_load_all(yaml_str):
            if doc:
                utils.create_from_dict(k8s_client, doc)
                name = doc.get('metadata', {}).get('name', 'unknown')
                print(f"  {name} created")
        return True
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        return False


def wait_for_job(name, timeout, namespace="default"):
    v1 = client.CoreV1Api()
    w = watch.Watch()
    
    try:
        stream = w.stream(
            v1.list_namespaced_pod, 
            namespace=namespace, 
            label_selector=f"job-name={name}", 
            timeout_seconds=timeout
        )
        
        for event in stream:
            pod = event['object']
            phase = pod.status.phase
            
            if phase == 'Succeeded':
                print(f"  {name} completed")
                w.stop()
                return True
                
            elif phase == 'Failed':
                reason = "Unknown failure"
                if pod.status.container_statuses:
                    terminated = pod.status.container_statuses[0].state.terminated
                    if terminated:
                        reason = terminated.reason or terminated.message
                        
                print(f"  WARNING: {name} failed: {reason}", file=sys.stderr)
                w.stop()
                return False

        print(f"  WARNING: {name} timed out after {timeout}s", file=sys.stderr)
        return False
        
    except Exception as e:
        print(f"  WARNING: Error watching {name}: {e}", file=sys.stderr)
        return False


def validate(memcached, jobs):
    """Validate policy structure and dependencies. Returns list of errors."""
    errors = []
    names = [j['name'] for j in jobs]

    if 'some-memcached' not in memcached:
        errors.append("Memcached block not found as first resource")
    if len(jobs) != 7:
        errors.append(f"Expected 7 batch jobs, found {len(jobs)}")
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        errors.append(f"Duplicate job names: {dupes}")

    by_name = {j['name']: j for j in jobs}
    for j in jobs:
        if j['after'] and j['after'] not in names:
            errors.append(f"{j['name']} depends on '{j['after']}' which is not in the policy")
        # Check circular
        current, seen = j['name'], set()
        while current:
            if current in seen:
                errors.append(f"Circular dependency involving {current}")
                break
            seen.add(current)
            current = by_name[current]['after'] if current in by_name else None

    # Print summary
    print(f"  Memcached: {'OK' if not any('Memcached' in e for e in errors) else 'MISSING'}")
    print(f"  Jobs: {len(jobs)}")
    for j in jobs:
        dep = f" (after {j['after']})" if j['after'] else ""
        print(f"    {j['name']}{dep}")

    if errors:
        print(f"\n  ERRORS:")
        for e in errors:
            print(f"    - {e}")
    else:
        print("  Validation passed.\n")

    return errors


def job_worker(job, timeout, events):
    name = job['name']
    dep = job['after']

    if dep: events[dep].wait()

    success = kubectl_create(job['yaml'])
    if not success: return
    success = wait_for_job(name, timeout)
    if not success:
        print(f"  Skipping {job['name']} (dependency {dep} failed)")
        return
    events[name].set()


def run(policy_path, timeout):
    print(f"Policy: {policy_path}")
    memcached, jobs = parse_policy(policy_path)

    if validate(memcached, jobs):
        sys.exit(1)

    events = { j['name']: threading.Event() for j in jobs }

    print(f"Launching DAG with {len(jobs)} jobs...")

    threads = [threading.Thread(target=job_worker, args=(j, timeout, events), daemon=True) for j in jobs]
    for t in threads:
        t.start()
    try:
        for t in threads:
            while t.is_alive():
                t.join(0.5) 
    except KeyboardInterrupt:
        print("\n  Terminating launcher and killing worker threads")
        sys.exit(1)

    print("Done.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Launch batch jobs with dependencies')
    parser.add_argument('policy', help='Path to policy YAML')
    parser.add_argument('--timeout', type=int, default=900, help='Per-job timeout in seconds')
    args = parser.parse_args()
    run(args.policy, args.timeout)
