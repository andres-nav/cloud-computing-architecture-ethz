#!/usr/bin/env bash
set -e

# Path to the existing script
RUN_SCRIPT="./automation_part2a.sh"

# All PARSEC benchmarks 
BENCHES=(
  barnes
  blackscholes
  canneal
  freqmine
  radix
  streamcluster
  vips
)

# All interference types
IBENCHES=(
  none
  l1d
  l1i
  l2
  llc
  cpu
  membw
)

for bench in "${BENCHES[@]}"; do
  for ibench in "${IBENCHES[@]}"; do
    echo "=========================================="
    echo "Running benchmark=$bench with interference=$ibench"
    echo "=========================================="

    "$RUN_SCRIPT" "$bench" "$ibench"

    echo
    echo "Finished benchmark=$bench with interference=$ibench"
    echo
  done
done

echo "All combinations finished."
