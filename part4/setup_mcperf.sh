#!/usr/bin/env bash

set -euo pipefail

REPO="https://github.com/eth-easl/memcache-perf-dynamic.git"
DIR="${HOME}/memcache-perf-dynamic"

sudo apt-get update -qq
sudo apt-get install -y git libevent-dev libzmq3-dev build-essential

if [ -d "$DIR" ]; then
    git -C "$DIR" pull
else
    git clone "$REPO" "$DIR"
fi

cd "$DIR"
make -j"$(nproc)"

echo "Done. Binary: ${DIR}/mcperf"
