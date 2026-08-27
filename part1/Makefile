ETHID            ?= ethid
KOPS_STATE_STORE ?= gs://cca-eth-2026-group-012-$(ETHID)/
export KOPS_STATE_STORE

SSH_KEY ?= ~/.ssh/id_ecdsa

# Target part: part1 | part2a | part2b | part3 | part4
PART    ?= part1
CLUSTER  = $(PART).k8s.local

# Interference type: cpu | l1d | l1i | l2 | llc | membw
IBENCH  ?= cpu

.PHONY: help create deploy validate setup status clean \
        start-memcached start-ibench stop-ibench label-parsec \
        get-pods get-results clean-jobs clean-bucket

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*##"}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

create: ## Create cluster config + SSH secret  [PART=partX]
	kops create -f $(PART).yaml
	kops create secret --name $(CLUSTER) sshpublickey admin -i $(SSH_KEY).pub

deploy: ## Deploy the cluster                  [PART=partX]
	kops update cluster --name $(CLUSTER) --yes --admin

validate: ## Wait until cluster is healthy      [PART=partX]
	kops validate cluster --name $(CLUSTER) --wait 10m

setup: create deploy validate ## Full cluster setup: create → deploy → validate  [PART=partX]

status: ## Show node status
	kubectl get nodes -o wide

clean: ## Delete the cluster                   [PART=partX]
	kops delete cluster --name $(CLUSTER) --yes

start-memcached: ## Launch memcached pod and expose port 11211
	kubectl create -f ../scripts/memcache-t1-cpuset.yaml
	kubectl expose pod some-memcached --name some-memcached-11211 \
		--type LoadBalancer --port 11211 --protocol TCP

start-ibench: ## Launch iBench interference     [IBENCH=cpu|l1d|l1i|l2|llc|membw]
	kubectl create -f ../interference/ibench-$(IBENCH).yaml

stop-ibench: ## Delete iBench interference pod  [IBENCH=cpu|l1d|l1i|l2|llc|membw]
	kubectl delete pod ibench-$(IBENCH)

label-parsec: ## Label the parsec node for scheduling
	kubectl label nodes \
		$$(kubectl get nodes --selector='cca-project-nodetype=parsec' \
		   -o jsonpath='{.items[0].metadata.name}') \
		cca-project-nodetype=parsec

get-pods: ## Show all pods with node placement
	kubectl get pods -o wide

get-results: ## Dump pod JSON and compute job execution times
	kubectl get pods -o json > results.json
	python3 ../scripts/get_time.py results.json

clean-jobs: ## Delete all running jobs and pods
	kubectl delete jobs --all
	kubectl delete pods --all

clean-bucket: ## Delete and recreate the GCS state store bucket
	gsutil rm -r $(KOPS_STATE_STORE)
	gsutil mb $(KOPS_STATE_STORE)
