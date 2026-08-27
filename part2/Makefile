ETHID            ?= ethid
KOPS_STATE_STORE ?= gs://cca-eth-2026-group-012-$(ETHID)/
export KOPS_STATE_STORE

PART ?= part2a
CLUSTER ?= $(PART).k8s.local
PART_YAML ?= $(PART).yaml

IBENCH ?= cpu
BENCH ?= barnes

IBENCH_YAML = ../interference/ibench-$(IBENCH).yaml
PARSEC_YAML = ../parsec-benchmarks/part2a/parsec-$(BENCH).yaml

.PHONY: help create deploy validate setup status start-ibench start-parsec clean-jobs delete-cluster clean clean-bucket

help: ## Show available commands
	@echo "Part 2a Makefile"
	@echo "Use: make -f Makefile.part2a <target> [VARIABLE=value]"
	@echo
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*##"}; {printf "  %-16s %s\n", $$1, $$2}'

create: ## Create cluster definition from part2a.yaml
	@echo "Creating cluster definition from $(PART_YAML)..."
	kops create -f $(PART_YAML)

deploy: ## Deploy the cluster
	@echo "Deploying cluster $(CLUSTER)..."
	kops update cluster --name $(CLUSTER) --yes --admin

validate: ## Wait until the cluster is healthy
	@echo "Waiting for cluster $(CLUSTER) to become healthy..."
	kops validate cluster --wait 10m

setup: create deploy validate ## Full setup: create -> deploy -> validate

status: ## Show cluster nodes
	kubectl get nodes -o wide

start-ibench: ## Start one interference pod
	@echo "Starting interference pod from $(IBENCH_YAML)..."
	kubectl create -f $(IBENCH_YAML)

start-parsec: ## Start one PARSEC benchmark job
	@echo "Starting PARSEC benchmark from $(PARSEC_YAML)..."
	kubectl create -f $(PARSEC_YAML)

clean-jobs: ## Delete all jobs and pods before the next run
	@echo "Deleting all Kubernetes jobs..."
	kubectl delete jobs --all
	@echo "Deleting all remaining pods..."
	kubectl delete pods --all

delete-cluster: ## Delete the whole cluster
	@echo "Deleting cluster $(CLUSTER)..."
	kops delete cluster --name $(CLUSTER) --yes

clean: delete-cluster ## Alias for cluster deletion

clean-bucket: ## Delete and recreate the KOPS state bucket
	@echo "This removes the bucket at $(KOPS_STATE_STORE) and recreates it."
	gsutil rm -r $(KOPS_STATE_STORE)
	gsutil mb $(KOPS_STATE_STORE)