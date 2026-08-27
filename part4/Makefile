ETHID            ?= ethid
KOPS_STATE_STORE ?= gs://cca-eth-2026-group-012-$(ETHID)/
export KOPS_STATE_STORE

CLUSTER  = part4.k8s.local
SSH_KEY ?= ~/.ssh/id_ecdsa
SSH_OPTS = -i $(SSH_KEY) -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null

# mcperf parameters
QPS_SEED        ?= 2345
QPS_INTERVAL    ?= 15
QPS_MIN         ?= 5000
QPS_MAX         ?= 110000
MCPERF_DURATION ?= 1800

# Controller to use (e.g. make run-controller CONTROLLER=andres-v1)
CONTROLLER ?= andres-v1

# Q1 parameters
THREADS ?= 2
CORES   ?= 2

# Question for collect-results (q3 or q4)
Q ?= q3

RESULTS_DIR        = results
TIMESTAMP          = $(shell date +%Y-%m-%d_%H:%M:%S)
REMOTE_HOME        = /home/ubuntu
REMOTE_MCPERF      = $(REMOTE_HOME)/memcache-perf-dynamic/mcperf
REMOTE_RESULTS     = $(REMOTE_HOME)/results

.PHONY: help gcloud-login \
        create deploy validate setup status clean \
        get-ips setup-memcached setup-mcperf setup-controller setup-all \
        run-agent run-mcperf-load run-mcperf-dynamic run-controller \
        run-q1 run-q1-all run-q3 run-q4 \
        collect-q1 collect-results clean-containers

help:
	@grep -E '^[a-zA-Z0-9_-]+:.*##' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*##"}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# Auth

gcloud-login: ## Re-authenticate with Google Cloud
	gcloud auth login
	gcloud auth application-default login

# Cluster lifecycle

create: ## Create cluster  [ETHID=your-eth-username]
	sed 's/<ethid>/$(ETHID)/g' part4.yaml | kops create -f -
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

# IP helpers

define ext-ip
$(shell kubectl get nodes --selector='cca-project-nodetype=$(1)' \
    -o jsonpath='{.items[0].status.addresses[?(@.type=="ExternalIP")].address}')
endef

define int-ip
$(shell kubectl get nodes --selector='cca-project-nodetype=$(1)' \
    -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
endef

get-ips: ## Print all node IPs
	@echo "memcache-server  int=$(call int-ip,memcached)  ext=$(call ext-ip,memcached)"
	@echo "client-agent     int=$(call int-ip,client-agent)  ext=$(call ext-ip,client-agent)"
	@echo "client-measure   int=$(call int-ip,client-measure)  ext=$(call ext-ip,client-measure)"

# VM setup

setup-memcached: ## Install memcached + Docker on memcache-server
	$(eval EXT := $(call ext-ip,memcached))
	$(eval INT := $(call int-ip,memcached))
	ssh $(SSH_OPTS) ubuntu@$(EXT) 'bash -s' < setup_memcached.sh $(INT)

setup-mcperf: ## Build mcperf on client-agent and client-measure
	$(eval AGENT   := $(call ext-ip,client-agent))
	$(eval MEASURE := $(call ext-ip,client-measure))
	ssh $(SSH_OPTS) ubuntu@$(AGENT)   'bash -s' < setup_mcperf.sh
	ssh $(SSH_OPTS) ubuntu@$(MEASURE) 'bash -s' < setup_mcperf.sh

setup-controller: ## Copy controller + logger to memcache-server  [CONTROLLER=andres-v1]
	$(eval EXT := $(call ext-ip,memcached))
	scp $(SSH_OPTS) controllers/$(CONTROLLER).py   ubuntu@$(EXT):$(REMOTE_HOME)/controller.py
	scp $(SSH_OPTS) ../scripts/scheduler_logger.py ubuntu@$(EXT):$(REMOTE_HOME)/scheduler_logger.py
	ssh $(SSH_OPTS) ubuntu@$(EXT) 'mkdir -p $(REMOTE_RESULTS)'

setup-monitor: ## Copy CPU monitor to memcache-server
	$(eval EXT := $(call ext-ip,memcached))
	scp $(SSH_OPTS) monitor_cpu.py ubuntu@$(EXT):$(REMOTE_HOME)/monitor_cpu.py

setup-all: setup-memcached setup-mcperf setup-controller ## Full VM setup

# Run targets

run-agent: ## Start mcperf agent on client-agent (background)
	$(eval AGENT := $(call ext-ip,client-agent))
	ssh $(SSH_OPTS) ubuntu@$(AGENT) 'pkill -f mcperf' 2>/dev/null || true
	ssh $(SSH_OPTS) ubuntu@$(AGENT) \
	    'nohup $(REMOTE_MCPERF) -T 8 -A > $(REMOTE_HOME)/agent.log 2>&1 &'

run-mcperf-load: ## Load memcached KV store
	$(eval MEM_INT := $(call int-ip,memcached))
	$(eval MEASURE := $(call ext-ip,client-measure))
	ssh $(SSH_OPTS) ubuntu@$(MEASURE) '$(REMOTE_MCPERF) -s $(MEM_INT) --loadonly'

run-mcperf-dynamic: ## Run dynamic QPS trace  [QPS_SEED, QPS_INTERVAL, QPS_MIN, QPS_MAX, MCPERF_DURATION]
	$(eval MEM_INT   := $(call int-ip,memcached))
	$(eval AGENT_INT := $(call int-ip,client-agent))
	$(eval MEASURE   := $(call ext-ip,client-measure))
	ssh $(SSH_OPTS) ubuntu@$(MEASURE) \
	    '$(REMOTE_MCPERF) -s $(MEM_INT) -a $(AGENT_INT) \
	        --noload -T 8 -C 8 -D 4 -Q 1000 -c 8 \
	        -t $(MCPERF_DURATION) \
	        --qps_interval $(QPS_INTERVAL) --qps_min $(QPS_MIN) --qps_max $(QPS_MAX) \
	        --qps_seed $(QPS_SEED) \
	        | tee $(REMOTE_HOME)/mcperf.txt'

run-controller: ## Start the scheduler on memcache-server
	$(eval EXT := $(call ext-ip,memcached))
	ssh $(SSH_OPTS) ubuntu@$(EXT) \
	    '$(REMOTE_HOME)/venv/bin/python3 -u $(REMOTE_HOME)/controller.py \
	        --log-dir $(REMOTE_RESULTS) \
	        2>&1 | tee $(REMOTE_RESULTS)/controller.log'

# Experiment shortcuts

run-q1: ## Q1: static QPS sweep 5K→125K  [THREADS=2 CORES=2]
	$(eval EXT       := $(call ext-ip,memcached))
	$(eval MEM_INT   := $(call int-ip,memcached))
	$(eval AGENT_INT := $(call int-ip,client-agent))
	$(eval MEASURE   := $(call ext-ip,client-measure))
	$(eval CORE_LIST := $(shell seq -s, 0 $$(($(CORES)-1))))
	ssh $(SSH_OPTS) ubuntu@$(EXT) 'pkill -f monitor_cpu.py' 2>/dev/null || true
	ssh $(SSH_OPTS) ubuntu@$(EXT) \
	    'nohup python3 $(REMOTE_HOME)/monitor_cpu.py $(REMOTE_HOME)/cpu.csv > /dev/null 2>&1 &'
	ssh $(SSH_OPTS) ubuntu@$(EXT) 'sudo sed -i "s/^-t [0-9]\+/-t $(THREADS)/" /etc/memcached.conf && sudo systemctl restart memcached'
	sleep 2
	$(eval MEM_PID := $(shell ssh $(SSH_OPTS) ubuntu@$(EXT) 'pgrep memcached'))
	ssh $(SSH_OPTS) ubuntu@$(EXT) \
	    'MEM_PID=$$(pgrep -n memcached); \
	     sudo taskset -a -cp $(CORE_LIST) $$MEM_PID; \
	     ACTUAL=$$(sudo taskset -c -p $$MEM_PID | awk "{print \$$NF}"); \
	     if [ "$$ACTUAL" != "$(CORE_LIST)" ] && [ "$$ACTUAL" != "0-$$(($(CORES)-1))" ]; then \
	         echo "Error: memcached not pinned to $(CORE_LIST), actual: $$ACTUAL"; exit 1; \
	     fi'
	ssh $(SSH_OPTS) ubuntu@$(MEASURE) '$(REMOTE_MCPERF) -s $(MEM_INT) --loadonly'
	ssh $(SSH_OPTS) ubuntu@$(MEASURE) \
	    '$(REMOTE_MCPERF) -s $(MEM_INT) -a $(AGENT_INT) \
	        --noload -T 8 -C 8 -D 4 -Q 1000 -c 8 -t 2 \
	        --scan 5000:125000:10000 | tee $(REMOTE_HOME)/mcperf.txt'

run-q1-all: ## Q1a: run all 9 thread/core configs
	for t in 1 2 3; do \
		for c in 1 2 3; do \
			echo "=== T=$$t C=$$c ==="; \
			$(MAKE) run-q1 THREADS=$$t CORES=$$c; \
			$(MAKE) collect-q1 THREADS=$$t CORES=$$c; \
		done; \
	done

run-q3: ## Q3: seed=2345, interval=15s, 30min
	$(MAKE) run-mcperf-load
	$(MAKE) run-mcperf-dynamic QPS_SEED=2345 QPS_INTERVAL=15

run-q4: ## Q4: seed=2345, interval=5s, 30min
	$(MAKE) run-mcperf-load
	$(MAKE) run-mcperf-dynamic QPS_SEED=2345 QPS_INTERVAL=5

# Results

collect-q1: ## Collect Q1 results  [THREADS=2 CORES=2]
	$(eval MEASURE := $(call ext-ip,client-measure))
	$(eval DIR     := $(RESULTS_DIR)/q1/T$(THREADS)_C$(CORES)/$(TIMESTAMP))
	@mkdir -p $(DIR)
	scp $(SSH_OPTS) "ubuntu@$(MEASURE):$(REMOTE_HOME)/mcperf.txt" $(DIR)/mcperf.txt 2>/dev/null || true
	ssh $(SSH_OPTS) ubuntu@$(MEASURE) '> $(REMOTE_HOME)/mcperf.txt' 2>/dev/null || true
	@echo "Saved to $(DIR)/" && ls -lh $(DIR)/

collect-results: ## Collect results into results/<Q>/<controller>/<timestamp>/  [Q=q3 CONTROLLER=andres-v1]
	$(eval EXT     := $(call ext-ip,memcached))
	$(eval MEASURE := $(call ext-ip,client-measure))
	$(eval DIR     := $(RESULTS_DIR)/$(Q)/$(CONTROLLER)/$(TIMESTAMP))
	@mkdir -p $(DIR)
	scp $(SSH_OPTS) "ubuntu@$(MEASURE):$(REMOTE_HOME)/mcperf.txt" $(DIR)/mcperf.txt 2>/dev/null || true
	scp $(SSH_OPTS) "ubuntu@$(EXT):$(REMOTE_RESULTS)/*.txt" $(DIR)/ 2>/dev/null || true
	scp $(SSH_OPTS) "ubuntu@$(EXT):$(REMOTE_RESULTS)/*.log" $(DIR)/ 2>/dev/null || true
	cp controllers/$(CONTROLLER).py $(DIR)/controller.py
	ssh $(SSH_OPTS) ubuntu@$(MEASURE) '> $(REMOTE_HOME)/mcperf.txt' 2>/dev/null || true
	@echo "Saved to $(DIR)/" && ls -lh $(DIR)/

clean-containers: ## Remove all Docker containers and reset memcached cores
	$(eval EXT := $(call ext-ip,memcached))
	ssh $(SSH_OPTS) ubuntu@$(EXT) 'sudo docker ps -aq | xargs -r sudo docker rm -f'
	ssh $(SSH_OPTS) ubuntu@$(EXT) 'rm -f $(REMOTE_RESULTS)/*.txt'
	ssh $(SSH_OPTS) ubuntu@$(EXT) 'sudo taskset -a -cp 0 $$(pgrep memcached)' 2>/dev/null || true
