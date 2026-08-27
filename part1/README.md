# Part 1 Runbook

## Step 0: Clean up

```sh
gcloud auth login
gcloud auth application-default login
make clean-bucket
```

## Step 1: Deploy the cluster

```sh
make setup PART=part1
```

## Step 2: Launch memcached

```sh
make start-memcached
```

```sh
kubectl get service some-memcached-11211   # note the EXTERNAL-IP
kubectl get pods -o wide                    # note the MEMCACHED_IP (pod IP)
```

## Step 3: Setup mcperf on client VMs

SSH into both client-agent and client-measure:

```sh
gcloud compute ssh --ssh-key-file ~/.ssh/id_ecdsa ubuntu@<client-agent-NAME> --zone europe-west1-b
gcloud compute ssh --ssh-key-file ~/.ssh/id_ecdsa ubuntu@<client-measure-NAME> --zone europe-west1-b
```

On both VMs, compile mcperf:

```sh
sudo apt-get update
sudo apt-get install libevent-dev libzmq3-dev git make g++ --yes
sudo sed -i 's/^Types: deb$/Types: deb deb-src/' /etc/apt/sources.list.d/ubuntu.sources
sudo apt-get update
sudo apt-get build-dep memcached --yes
cd && git clone https://github.com/shaygalon/memcache-perf.git
cd memcache-perf
git checkout 0afbe9b
make
```

## Step 4: Run experiments (repeat each config 3× minimum)

On client-agent (keep running):

```sh
./mcperf -T 8 -A
```

On client-measure (for each experiment):

```sh
./mcperf -s MEMCACHED_IP --loadonly
./mcperf -s MEMCACHED_IP -a INTERNAL_AGENT_IP \
    --noload -T 8 -C 8 -D 4 -Q 1000 -c 8 -w 2 -t 5 \
    --scan 5000:80000:5000
```

## Step 5: Run through all 7 configurations

For each of these, run the mcperf command above 3 times and save the output:

Wait for each ibench pod to show READY 1/1 before running mcperf (`make get-pods` to check).

1. No interference, just run mcperf
2. CPU `make start-ibench IBENCH=cpu` → run mcperf → `make stop-ibench IBENCH=cpu`
3. L1D `make start-ibench IBENCH=l1d` → run mcperf → `make stop-ibench IBENCH=l1d`
4. L1I `make start-ibench IBENCH=l1i` → run mcperf → `make stop-ibench IBENCH=l1i`
5. L2 `make start-ibench IBENCH=l2` → run mcperf → `make stop-ibench IBENCH=l2`
6. LLC `make start-ibench IBENCH=llc` → run mcperf → `make stop-ibench IBENCH=llc`
7. MemBW `make start-ibench IBENCH=membw` → run mcperf → `make stop-ibench IBENCH=membw`

## Step 6: Collect data & tear down

Save the client-measure output for each run (QPS vs p95 latency). Then:

```sh
make clean PART=part1
```