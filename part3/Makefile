ETHID            ?= ethid
KOPS_STATE_STORE ?= gs://cca-eth-2026-group-012-$(ETHID)/
export KOPS_STATE_STORE

CLUSTER  = part3.k8s.local
SSH_KEY ?= ~/.ssh/cloud-computing
SSH_OPTS = -i $(SSH_KEY) -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null

# Policy file to run (e.g. make run-policy POLICY=andres)
POLICY ?= andres-v1

# Number of runs for automation (e.g. make run-automate RUNS=3)
RUNS ?= 3

RESULTS_DIR   = results
TIMESTAMP     = $(shell date +%Y-%m-%d_%H:%M:%S)
REMOTE_HOME   = /home/ubuntu
REMOTE_MCPERF = $(REMOTE_HOME)/memcache-perf-dynamic/mcperf

.PHONY: help gcloud-login \
        create deploy validate setup status clean \
        get-ips setup-mcperf \
        start-memcached run-policy run-automate \
        run-agent-a run-agent-b run-mcperf \
        get-results collect-results \
        clean-jobs clean-bucket

help:
	@grep -E '^[a-zA-Z0-9_-]+:.*##' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*##"}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# Auth

gcloud-login: ## Re-authenticate with Google Cloud
	gcloud auth login
	gcloud auth application-default login

# Cluster lifecycle

create: ## Create cluster  [ETHID=your-eth-username]
	sed 's/<ethid>/$(ETHID)/g' part3.yaml | kops create -f -
	kops create secret --name $(CLUSTER) sshpublickey admin -i $(SSH_KEY).pub

deploy: ## Deploy the cluster
	kops update cluster --name $(CLUSTER) --yes --admin

validate: ## Wait until cluster is healthy
	kops validate cluster --name $(CLUSTER) --wait 10m

setup: create deploy validate ## Full cluster setup

status: ## Show node IPs
	kubectl get nodes -o wide

clean: ## Delete the cluster
	kops delete cluster --name $(CLUSTER) --yes
	$(MAKE) clean-bucket

clean-bucket: ## Delete and recreate the KOPS state bucket
	@echo "This removes the bucket at $(KOPS_STATE_STORE) and recreates it."
	gsutil rm -r $(KOPS_STATE_STORE)
	gsutil mb $(KOPS_STATE_STORE)

# IP helpers

define ext-ip
$(shell kubectl get nodes \
    --selector='cca-project-nodetype=$(1)' \
    -o jsonpath='{.items[0].status.addresses[?(@.type=="ExternalIP")].address}')
endef

define int-ip
$(shell kubectl get nodes \
    --selector='cca-project-nodetype=$(1)' \
    -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
endef

get-ips: ## Print all node IPs
	@echo "node-a-8core    int=$(call int-ip,node-a-8core)   ext=$(call ext-ip,node-a-8core)"
	@echo "node-b-4core    int=$(call int-ip,node-b-4core)   ext=$(call ext-ip,node-b-4core)"
	@echo "client-agent-a  int=$(call int-ip,client-agent-a) ext=$(call ext-ip,client-agent-a)"
	@echo "client-agent-b  int=$(call int-ip,client-agent-b) ext=$(call ext-ip,client-agent-b)"
	@echo "client-measure  int=$(call int-ip,client-measure) ext=$(call ext-ip,client-measure)"

# mcperf setup (run on all 3 client VMs)

setup-mcperf: ## Build mcperf on all client VMs
	$(eval AGENT_A  := $(call ext-ip,client-agent-a))
	$(eval AGENT_B  := $(call ext-ip,client-agent-b))
	$(eval MEASURE  := $(call ext-ip,client-measure))
	ssh $(SSH_OPTS) ubuntu@$(AGENT_A)  'bash -s' < setup_mcperf.sh
	ssh $(SSH_OPTS) ubuntu@$(AGENT_B)  'bash -s' < setup_mcperf.sh
	ssh $(SSH_OPTS) ubuntu@$(MEASURE)  'bash -s' < setup_mcperf.sh

# Workload management (Kubernetes)

start-memcached: ## Deploy memcached from policy and expose it (removes it first if it already exists)  [POLICY=andres-v1]
	-kubectl delete svc some-memcached-11211 2>/dev/null || true
	-kubectl delete pod some-memcached 2>/dev/null || true
	@while kubectl get pod some-memcached >/dev/null 2>&1; do sleep 1; done
	awk '/^---/{n++} n==0' policies/$(POLICY).yaml | kubectl create -f -
	kubectl expose pod some-memcached --name some-memcached-11211 \
		--type LoadBalancer --port 11211 --protocol TCP
	kubectl wait --for=condition=Ready pod/some-memcached --timeout=120s

run-policy: ## Deploy batch jobs from policy with dependencies  [POLICY=andres-v1]
	python3 launcher.py policies/$(POLICY).yaml --timeout 900

run-automate: ## Full automated run: memcached + agents + mcperf + N batch runs  [RUNS=3]
	$(MAKE) clean-jobs
	$(MAKE) start-memcached
	$(MAKE) run-agent-a
	$(MAKE) run-agent-b
	$(MAKE) run-mcperf &
	@sleep 5
	for i in $$(seq 1 $(RUNS)); do \
		echo "========== Run $$i/$(RUNS) =========="; \
		python3 launcher.py policies/$(POLICY).yaml --timeout 900; \
		$(MAKE) collect-results; \
		$(MAKE) clean-jobs; \
	done
	@echo "All $(RUNS) runs complete for policy $(POLICY)."

clean-jobs: ## Delete batch jobs and pods (keeps memcached running, idempotent)
	-kubectl delete jobs --all 2>/dev/null || true
	-kubectl delete pods -l 'name!=some-memcached' 2>/dev/null || true

# mcperf load generation

run-agent-a: ## Start mcperf agent on client-agent-a (idempotent, verifies running)
	$(eval AGENT_A := $(call ext-ip,client-agent-a))
	ssh $(SSH_OPTS) ubuntu@$(AGENT_A) 'pkill mcperf || true; sleep 1'
	ssh $(SSH_OPTS) ubuntu@$(AGENT_A) \
	    'nohup $(REMOTE_MCPERF) -T 2 -A > $(REMOTE_HOME)/agent_a.log 2>&1 &'
	@sleep 2
	ssh $(SSH_OPTS) ubuntu@$(AGENT_A) 'pgrep mcperf >/dev/null && echo "agent-a running" || { echo "agent-a FAILED"; exit 1; }'

run-agent-b: ## Start mcperf agent on client-agent-b (idempotent, verifies running)
	$(eval AGENT_B := $(call ext-ip,client-agent-b))
	ssh $(SSH_OPTS) ubuntu@$(AGENT_B) 'pkill mcperf || true; sleep 1'
	ssh $(SSH_OPTS) ubuntu@$(AGENT_B) \
	    'nohup $(REMOTE_MCPERF) -T 4 -A > $(REMOTE_HOME)/agent_b.log 2>&1 &'
	@sleep 2
	ssh $(SSH_OPTS) ubuntu@$(AGENT_B) 'pgrep mcperf >/dev/null && echo "agent-b running" || { echo "agent-b FAILED"; exit 1; }'

run-mcperf: ## Load memcached and run 30K QPS measurement (idempotent, kills existing)
	$(eval MEM_INT    := $(shell kubectl get pod some-memcached -o jsonpath='{.status.podIP}'))
	$(eval AGENT_A_INT := $(call int-ip,client-agent-a))
	$(eval AGENT_B_INT := $(call int-ip,client-agent-b))
	$(eval MEASURE    := $(call ext-ip,client-measure))
	ssh $(SSH_OPTS) ubuntu@$(MEASURE) 'pkill mcperf || true; sleep 1'
	ssh $(SSH_OPTS) ubuntu@$(MEASURE) \
	    '$(REMOTE_MCPERF) -s $(MEM_INT) --loadonly'
	ssh $(SSH_OPTS) ubuntu@$(MEASURE) \
	    '$(REMOTE_MCPERF) -s $(MEM_INT) \
	        -a $(AGENT_A_INT) -a $(AGENT_B_INT) \
	        --noload -T 6 -C 4 -D 4 -Q 1000 -c 4 -t 10 \
	        --scan 30000:30500:5 \
	        | tee $(REMOTE_HOME)/mcperf.txt'

# Results

get-results: ## Fetch pod JSON and compute job execution times (run after all jobs complete)
	kubectl get pods -o json > results.json
	python3 ../scripts/get_time.py results.json

collect-results: ## SCP results into results/<policy>/<timestamp>/
	$(eval MEASURE := $(call ext-ip,client-measure))
	$(eval DIR     := $(RESULTS_DIR)/$(POLICY)/$(TIMESTAMP))
	@mkdir -p $(DIR)
	kubectl get pods -o json > $(DIR)/pods.json
	python3 ../scripts/get_time.py $(DIR)/pods.json | tee $(DIR)/times.txt
	cp policies/$(POLICY).yaml $(DIR)/policy.yaml
	scp $(SSH_OPTS) "ubuntu@$(MEASURE):$(REMOTE_HOME)/mcperf.txt" $(DIR)/mcperf.txt 2>/dev/null || true
	ssh $(SSH_OPTS) ubuntu@$(MEASURE) '> $(REMOTE_HOME)/mcperf.txt' 2>/dev/null || true
	@echo "Saved to $(DIR)/" && ls -lh $(DIR)/

prepull-images: ## Manually download all batch job images on the worker nodes
	$(eval NODE_A := $(call ext-ip,node-a-8core))
	$(eval NODE_B := $(call ext-ip,node-b-4core))
	$(eval IMAGES := anakli/cca:parsec_blackscholes anakli/cca:parsec_canneal anakli/cca:parsec_freqmine anakli/cca:parsec_vips anakli/cca:splash2x_radix anakli/cca:parsec_streamcluster anakli/cca:splash2x_barnes)
	@echo "Pulling images directly on node-a-8core..."
	ssh $(SSH_OPTS) ubuntu@$(NODE_A) 'for img in $(IMAGES); do sudo crictl pull $$img; done'
	@echo "Pulling images directly on node-b-4core..."
	ssh $(SSH_OPTS) ubuntu@$(NODE_B) 'for img in $(IMAGES); do sudo crictl pull $$img; done'
	@echo "All images pre-pulled successfully."
