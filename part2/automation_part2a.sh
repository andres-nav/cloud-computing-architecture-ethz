#!/usr/bin/env bash
set -e

if [[ -z "$1" ]]; then
  echo "Error: Benchmark name required."
  echo "Usage: $0 <benchmark_name> [interference_type]"
  exit 1
fi

BENCH=$1
IBENCH=${2:-none}

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)

OUTDIR="$SCRIPT_DIR/results/part2a/${BENCH}_${IBENCH}"
mkdir -p "$OUTDIR"

TIMESTAMP=$(date +"%Y-%m-%d_%H:%M:%S")
LOGFILE="$OUTDIR/${TIMESTAMP}.log"

if [[ "$IBENCH" != "none" ]]; then
  case "$IBENCH" in
    cpu)   PROC="cpu" ;;
    membw) PROC="memBw" ;;
    l1d)   PROC="l1d" ;;
    l1i)   PROC="l1i" ;;
    l2)    PROC="l2" ;;
    llc)   PROC="llc" ;;
    *) echo "Error: Unknown interference type: $IBENCH"; exit 1 ;;
  esac

  echo "Starting interference: $IBENCH"
  kubectl create -f "$SCRIPT_DIR/../interference/ibench-${IBENCH}.yaml"

  echo "Waiting for interference to be ready..."
  kubectl wait \
    --for=condition=Ready \
    "pod/ibench-${IBENCH}" \
    --timeout=300s

  echo "Waiting for interference process $PROC to start..."
  until kubectl exec "ibench-${IBENCH}" -- sh -c "pgrep -af '$PROC' >/dev/null" 2>/dev/null; do
    sleep 1
  done

  echo "Interference is running."
else
  echo "Running baseline without interference."
fi

echo "Starting PARSEC benchmark: $BENCH"
kubectl create -f "$SCRIPT_DIR/../parsec-benchmarks/part2a/parsec-${BENCH}.yaml"

echo "Waiting for benchmark to finish..."
kubectl wait \
  --for=condition=complete \
  "job/parsec-${BENCH}" \
  --timeout=1h

echo "Collecting logs..."
POD_NAME=$(kubectl get pods --selector=job-name="parsec-${BENCH}" --output=jsonpath='{.items[0].metadata.name}')
if [[ -n "$POD_NAME" ]]; then
  kubectl logs "$POD_NAME" > "$LOGFILE"
else
  echo "Warning: Could not find pod for job parsec-${BENCH} to collect logs."
fi

echo "Cleaning up..."
kubectl delete jobs --all
kubectl delete pods --all

echo "Done."
