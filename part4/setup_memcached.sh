#!/usr/bin/env bash
# Install and configure memcached + Docker on the memcache-server VM.

set -euo pipefail
# silence `debconf` prompt questions
export DEBIAN_FRONTEND=noninteractive
INTERNAL_IP="${1:?Usage: $0 <INTERNAL_IP>}"
CONF="/etc/memcached.conf"

sudo apt-get update -qq
sudo apt-get install -y memcached libmemcached-tools

# Configure: 1024 MB memory, bind to internal IP, 4 threads
sudo sed -i 's/^-m [0-9]\+/-m 1024/'          "$CONF"
sudo sed -i "s/^-l .*/-l ${INTERNAL_IP}/"      "$CONF"
grep -q '^-t ' "$CONF" \
    && sudo sed -i 's/^-t [0-9]\+/-t 3/' "$CONF" \
    || echo "-t 3" | sudo tee -a "$CONF" > /dev/null

sudo systemctl restart memcached
sudo systemctl enable memcached
sudo systemctl status memcached --no-pager

sudo apt-get install -y ca-certificates curl gnupg lsb-release
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --batch --yes --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update -qq
# Dpkg options silence configuration conflicts, e.g if `/etc/containerd/config.toml` already exists (which it does)
sudo apt-get install -y \
    -o Dpkg::Options::="--force-confdef" \
    -o Dpkg::Options::="--force-confold" \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin
sudo usermod -aG docker "${USER}"

sudo apt-get install -y python3 python3-venv
python3 -m venv "${HOME}/venv"
"${HOME}/venv/bin/pip" install docker psutil

echo "Done. memcached listening on ${INTERNAL_IP}:11211. Re-login for docker group."
