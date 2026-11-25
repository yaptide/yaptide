.PHONY: help build build-no-cache up start down clean logs test status shell logs-slurmctld logs-slurmdbd update-slurm reload-slurm version set-version build-all rebuild jobs quick-test run-examples scale-cpu-workers

# Default target
.DEFAULT_GOAL := help

# Supported Slurm versions
SUPPORTED_VERSIONS := 25.11.4
DEFAULT_VERSION := 25.11.4

# Auto-detect profiles based on .env configuration
ELASTICSEARCH_HOST := $(shell grep -E '^ELASTICSEARCH_HOST=' .env 2>/dev/null | cut -d= -f2)

# Build profile flags
PROFILES :=
ifdef ELASTICSEARCH_HOST
    PROFILES += --profile monitoring
endif
PROFILE_FLAG := $(PROFILES)

# Colors for help output
CYAN := $(shell tput -Txterm setaf 6)
RESET := $(shell tput -Txterm sgr0)

help:  ## Show this help message
	@echo "Slurm Docker Cluster - Available Commands"
	@echo "=========================================="
	@echo ""
	@echo "Cluster Management:"
	@printf "  ${CYAN}%-20s${RESET} %s\n" "build" "Build Docker images"
	@printf "  ${CYAN}%-20s${RESET} %s\n" "build-no-cache" "Build Docker images without cache"
	@printf "  ${CYAN}%-20s${RESET} %s\n" "up" "Start containers"
	@printf "  ${CYAN}%-20s${RESET} %s\n" "down" "Stop containers"
	@printf "  ${CYAN}%-20s${RESET} %s\n" "clean" "Remove containers and volumes"
	@printf "  ${CYAN}%-20s${RESET} %s\n" "scale-cpu-workers" "Scale CPU workers (requires N=...)"
	@printf "  ${CYAN}%-20s${RESET} %s\n" "rebuild" "Clean, rebuild, and start"
	@echo ""
	@echo "Quick Commands:"
	@printf "  ${CYAN}%-15s${RESET} %s\n" "jobs" "View job queue"
	@printf "  ${CYAN}%-15s${RESET} %s\n" "status" "Show cluster status"
	@printf "  ${CYAN}%-15s${RESET} %s\n" "logs" "Show all container logs"
	@printf "  ${CYAN}%-15s${RESET} %s\n" "logs-slurmctld" "Show slurmctld logs"
	@printf "  ${CYAN}%-15s${RESET} %s\n" "logs-slurmdbd" "Show slurmdbd logs"
	@echo ""
	@echo "Configuration Management:"
	@printf "  ${CYAN}%-15s${RESET} %s\n" "update-slurm" "Update config files (requires FILES=\"...\")"
	@printf "  ${CYAN}%-15s${RESET} %s\n" "reload-slurm" "Reload Slurm config without restart"
	@echo ""
	@echo "Development & Testing:"
	@printf "  ${CYAN}%-15s${RESET} %s\n" "shell" "Open shell in slurmctld"
	@printf "  ${CYAN}%-15s${RESET} %s\n" "test" "Run test suite"
	@printf "  ${CYAN}%-15s${RESET} %s\n" "test-monitoring" "Run monitoring profile tests"
	@printf "  ${CYAN}%-15s${RESET} %s\n" "quick-test" "Submit a quick test job"
	@printf "  ${CYAN}%-15s${RESET} %s\n" "run-examples" "Run example jobs"
	@echo ""
	@echo "Multi-Version Support:"
	@printf "  ${CYAN}%-15s${RESET} %s\n" "version" "Show current Slurm version"
	@printf "  ${CYAN}%-15s${RESET} %s\n" "set-version" "Set Slurm version (requires VER=...)"
	@printf "  ${CYAN}%-15s${RESET} %s\n" "build-all" "Build all supported versions"
	@printf "  ${CYAN}%-15s${RESET} %s\n" "test-all" "Test all supported versions"
	@echo ""
	@echo "Examples:"
	@echo "  make update-slurm FILES=\"slurm.conf slurmdbd.conf\""
	@echo "  make set-version VER=25.11.4"
	@echo "  make scale-cpu-workers N=3"
	@echo ""
	@echo "Monitoring:"
	@echo "  Enable:  Set ELASTICSEARCH_HOST=http://elasticsearch:9200 in .env"
	@echo "  Disable: Comment out or remove ELASTICSEARCH_HOST from .env"

build:  ## Build Docker images
	docker compose --progress plain build

build-no-cache:  ## Build Docker images without cache
	docker compose --progress plain build --no-cache

up:  ## Start containers (auto-enables monitoring if ELASTICSEARCH_HOST is set in .env)
	docker compose $(PROFILE_FLAG) up -d

down:  ## Stop containers
	docker compose $(PROFILE_FLAG) down

clean:  ## Remove containers and volumes
	docker compose $(PROFILE_FLAG) down -v

logs:  ## Show container logs
	docker compose logs -f

status:  ## Show cluster status
	@echo "=== Containers ==="
	@docker compose ps
	@echo ""
	@echo "=== Cluster ==="
	@docker exec slurmctld sinfo 2>/dev/null || echo "Not ready"

shell:  ## Open shell in slurmctld
	docker exec -it slurmctld bash

logs-slurmctld:  ## Show slurmctld logs
	docker compose logs -f slurmctld

logs-slurmdbd:  ## Show slurmdbd logs
	docker compose logs -f slurmdbd

quick-test:  ## Submit a quick test job
	docker exec slurmctld bash -c "cd /data && sbatch --wrap='hostname' && sleep 3 && squeue && cat slurm-*.out 2>/dev/null | tail -5"

jobs:  ## View job queue
	docker exec slurmctld squeue

reload-slurm:  ## Reload Slurm config without restart (after live editing)
	@echo "Reloading Slurm configuration..."
	docker exec slurmctld scontrol reconfigure
	@echo "✓ Configuration reloaded"

scale-cpu-workers:  ## Scale CPU workers (usage: make scale-cpu-workers N=3)
	@if [ -z "$(N)" ]; then \
		echo "Error: N parameter required. Usage: make scale-cpu-workers N=3"; \
		exit 1; \
	fi
	docker compose $(PROFILE_FLAG) up -d --scale cpu-worker=$(N) --no-recreate
	@echo "Waiting for dynamic workers to register..."; \
	sleep 10; \
	LIVE_NODES=$$(docker compose $(PROFILE_FLAG) ps cpu-worker -q 2>/dev/null \
		| while read cid; do \
			docker exec "$$cid" hostname 2>/dev/null; \
		done | sort); \
	SLURM_NODES=$$(docker exec slurmctld scontrol show nodes 2>/dev/null \
		| grep -o 'NodeName=c[0-9]*' | cut -d= -f2 | sort); \
	STALE_NODES=$$(comm -23 <(echo "$$SLURM_NODES") <(echo "$$LIVE_NODES") | paste -sd, -); \
	if [ -n "$$STALE_NODES" ]; then \
		echo "Removing stale dynamic nodes: $$STALE_NODES"; \
		docker exec slurmctld scontrol delete nodename=$$STALE_NODES; \
	fi; \
	docker exec slurmctld sinfo

# Multi-Version Support Targets

version:  ## Show current Slurm version
	@if [ -f .env ]; then \
		grep SLURM_VERSION .env || echo "SLURM_VERSION not set (default: $(DEFAULT_VERSION))"; \
	else \
		echo "No .env file found (default: $(DEFAULT_VERSION))"; \
	fi

set-version:  ## Set Slurm version (usage: make set-version VER=25.05.6)
	@if [ -z "$(VER)" ]; then \
		echo "Error: VER parameter required. Usage: make set-version VER=25.05.6"; \
		echo "Supported versions: $(SUPPORTED_VERSIONS)"; \
		exit 1; \
	fi
	@echo "SLURM_VERSION=$(VER)" > .env
	@echo "✓ Set SLURM_VERSION=$(VER) in .env"
	@echo "Run 'make rebuild' to rebuild with this version"

build-all:  ## Build Docker images for all supported versions
	@echo "Building all supported Slurm versions..."
	@for version in $(SUPPORTED_VERSIONS); do \
		echo ""; \
		echo "========================================"; \
		echo "Building Slurm $$version"; \
		echo "========================================"; \
		echo "SLURM_VERSION=$$version" > .env; \
		docker compose build || exit 1; \
		echo "✓ Built slurm-docker-cluster:$$version"; \
	done
	@echo ""
	@echo "========================================"; \
	echo "✓ All versions built successfully"; \
	echo "========================================"; \
	docker images | grep slurm-docker-cluster

rebuild: clean build up status
