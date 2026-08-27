# Part 2b README

## Prepare credentials and bucket

```sh
gcloud auth login
gcloud auth application-default login
```

```sh
export KOPS_STATE_STORE=gs://cca-eth-2026-group-012-<ethid>/
PROJECT=`gcloud config get-value project`
```


## Clean and recreate the bucket

```sh
make clean-bucket
```

## Create and deploy the cluster

Make sure to adapt your ssh-key

```sh
make setup PART=part2b
```

## Check that the nodes are up

```sh
make status
```

## Label the PARSEC node
replace the \<parsec-server-name\> with the name of the parsec server observed in the output of the kubectl get nodes command

```sh
kubectl label nodes <parsec-server-name> cca-project-nodetype=parsec
```

### Verify the label

```sh
kubectl get nodes --show-labels
```

## Run with full automation

Before starting the each run, change the number of threads in the yaml file accordingly in the `parsec-benchmarks/part2b`files in line 15 after `-n` to the desired number.

Run for `N = 1, 2, 4, 8`:

```sh
./all-automation_part2b.sh <N>
```

## Run half automated

Run for every combination of `N` and parsec benchmark:

```sh
./automation_part2b.sh <Benchmark> <N>
```

## Delete the cluster

```sh
kops delete cluster part2b.k8s.local --yes
```
