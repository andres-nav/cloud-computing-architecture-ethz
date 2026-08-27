#!/usr/bin/env bash
set -e

RUN_SCRIPT="./automation_part2b.sh"

BENCHES=(
  barnes
  blackscholes
  canneal
  freqmine
  radix
  streamcluster
  vips
)

THREADS=(1 2 4 8)

for bench in "${BENCHES[@]}"; do
  for N in "${THREADS[@]}"; do
    echo "=========================================="
    echo "Running benchmark=$bench with threads=$N"
    echo "=========================================="

    "$RUN_SCRIPT" "$bench" "$N"

    echo
    echo "Finished benchmark=$bench with threads=$N"
    echo
  done
done

echo "All combinations finished."
