#!/usr/bin/env bash
# Build the augmented mcperf on a client VM (client-agent-a, client-agent-b, or client-measure).
# Usage: ssh <host> 'bash -s' < setup_mcperf.sh
set -euo pipefail

REPO="https://github.com/eth-easl/memcache-perf-dynamic.git"
DIR="${HOME}/memcache-perf-dynamic"

# Enable deb-src (required for build-dep on Ubuntu 24.04)
sudo sed -i 's/^Types: deb$/Types: deb deb-src/' /etc/apt/sources.list.d/ubuntu.sources
sudo apt-get update -qq
sudo apt-get install -y libevent-dev libzmq3-dev git make g++
sudo apt-get build-dep -y memcached

if [ -d "$DIR" ]; then
    git -C "$DIR" pull
else
    git clone "$REPO" "$DIR"
fi

cd "$DIR"
make -j"$(nproc)"

echo "Done. Binary: ${DIR}/mcperf"
