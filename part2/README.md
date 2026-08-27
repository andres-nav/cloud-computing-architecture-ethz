# Part 2a README


**Important:** run experiments **sequentially**. Do not run multiple PARSEC jobs at once.


## Prepare credentials and bucket

```sh
gcloud auth login
gcloud auth application-default login
```

```sh
export KOPS_STATE_STORE=gs://cca-eth-2026-group-012-<ethid>/
PROJECT=`gcloud config get-value project`
```


### Clean and recreate the bucket

```sh
make clean-bucket
```

---

## Create and deploy the cluster

Make sure to adapt your ssh-key

```sh
make setup PART=part2a
```

OR:

```sh
kops create -f part2a.yaml
kops update cluster --name part2a.k8s.local --yes --admin
kops validate cluster --wait 10m
```

---

## Check that the nodes are up

```sh
make status
```

or

```sh
kubectl get nodes -o wide
```

---

## Label the PARSEC node
replace the \<parsec-server-name\> with the name of the parsec server observed in the output of the kubectl get nodes command

NOTE: this might not be necessary, since `part2a.yaml` already specifies `spec: cca-project-nodetype: "parsec"`.
```sh
kubectl label nodes <parsec-server-name> cca-project-nodetype=parsec
```

### Verify the label

```sh
kubectl get nodes --show-labels
```

---

# Run with automation of single runs
Run for each combination:

For no interference use "none"

```sh
./automation_part2a.sh <parsec> <interference>
```

## Delete the Cluster

```sh
kops delete cluster part2a.k8s.local --yes
```

# Run with automation for ALL runs

Run once

```sh
./all-automation_part2a.sh
```

## Delete the Cluster

```sh
kops delete cluster part2a.k8s.local --yes
```

# Run without the automation

## Run baseline experiment with no interference

### Start the PARSEC job

```sh
kubectl create -f parsec-benchmarks/part2a/parsec-<JobType>.yaml
```

OR:

```sh
make start-parsec BENCH=<JobType>
```

### Watch the job / pod

```sh
kubectl get jobs
```

### Collect the logs

Save them to a file:

the job name needs to match the one you get from kubectl get jobs

```sh
kubectl logs $(kubectl get pods --selector=job-name=<job_name> --output=jsonpath='{.items[*].metadata.name}') > <filePath>.txt>
```

### Clean up

```sh
make clean-jobs
```

OR:

```sh
kubectl delete jobs --all
kubectl delete pods --all
```

always clean up before the next run.

---

## Run an experiment with interference

### Start the interference pod

```sh
make start-ibench IBENCH=<interference>
```

OR:

```sh
kubectl create -f interference/ibench-<interference>.yaml
```

### Wait until interference is really running
SSH into the parsec-server

External IP over:

```sh
kubectl get pods -o wide
```

```sh
ssh -i ~/.ssh/cloud-computing ubuntu@<External-IP>
```

Run and wait for interference to start:

```sh
htop
```

### Start the PARSEC benchmark job

```sh
kubectl create -f parsec-benchmarks/part2a/<parsec-benchmark>.yaml
```

or:

```sh
make start-parsec BENCH=<Benchmark>
```

### Monitor progress

```sh
kubectl get jobs
```

### Collect the logs

```sh
kubectl logs $(kubectl get pods --selector=job-name=<job_name> --output=jsonpath='{.items[*].metadata.name}') > <filePath>.txt
```

### Clean up

```sh
make clean-jobs
```

OR:

```sh
kubectl delete jobs --all
kubectl delete pods --all
```

---

## Delete the Cluster

```sh
kops delete cluster part2a.k8s.local --yes
```

# Interference types

- no interference
- `cpu`
- `l1d`
- `l1i`
- `l2`
- `llc`
- `membw`

---

# PARSEC benchmarks

- `barnes`
- `blackscholes`
- `canneal`
- `freqmine`
- `radix`
- `streamcluster`
- `vips`

