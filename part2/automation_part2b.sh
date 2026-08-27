#!/usr/bin/env bash
set -e

if [[ -z "$1" ]] || [[ -z "$2" ]]; then
  echo "Error: Benchmark name and thread count required."
  echo "Usage: $0 <benchmark_name> <threads>"
  exit 1
fi

BENCH=$1
THREADS=$2

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)

OUTDIR="$SCRIPT_DIR/results/part2b/${BENCH}_${THREADS}t"
mkdir -p "$OUTDIR"

TIMESTAMP=$(date +"%Y-%m-%d_%H:%M:%S")
LOGFILE="$OUTDIR/${TIMESTAMP}.log"

YAML_TEMPLATE="$SCRIPT_DIR/../parsec-benchmarks/part2b/parsec-${BENCH}.yaml"
TEMP_YAML="/tmp/parsec-${BENCH}-${THREADS}t.yaml"

echo "Creating temporary YAML for $BENCH with $THREADS threads..."
sed "/args:/ s/-n 1/-n ${THREADS}/g" "$YAML_TEMPLATE" > "$TEMP_YAML"

echo "Starting PARSEC benchmark: $BENCH with $THREADS threads"
kubectl create -f "$TEMP_YAML"

echo "Waiting for benchmark to finish..."
kubectl wait \
  --for=condition=complete \
  "job/parsec-${BENCH}" \
  --timeout=600s

echo "Collecting logs..."
POD_NAME=$(kubectl get pods --selector=job-name="parsec-${BENCH}" --output=jsonpath='{.items[*].metadata.name}')
kubectl logs "$POD_NAME" > "$LOGFILE"

echo "Cleaning up job and temporary YAML..."
kubectl delete -f "$TEMP_YAML"
rm "$TEMP_YAML"

echo "Done. Logs saved to $LOGFILE"
