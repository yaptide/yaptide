# Slurm Docker Cluster

**Slurm Docker Cluster** is a multi-container Slurm cluster designed for rapid
deployment using Docker Compose. This repository simplifies the process of
setting up a robust Slurm environment for development, testing, or lightweight
usage.

## 🏁 Quick Start

**Requirements:** [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)

```bash
git clone https://github.com/giovtorres/slurm-docker-cluster.git
cd slurm-docker-cluster
cp .env.example .env

# Option A: Pull pre-built image from Docker Hub (fastest)
docker pull giovtorres/slurm-docker-cluster:latest
docker tag giovtorres/slurm-docker-cluster:latest slurm-docker-cluster:25.11.4

# Option B: Build from source
make build

# Then, start the cluster
make up
```

**Supported Slurm versions:** 25.11

**Supported architectures (auto-detected):** AMD64, ARM64

## 📦 What's Included

**Containers:**

- **mysql** - Job and cluster database
- **slurmdbd** - Database daemon for accounting
- **slurmctld** - Controller for job scheduling
- **slurmrestd** - REST API daemon (HTTP/JSON access)
- **c1, c2** - CPU compute nodes (dynamically scalable)
- **elasticsearch** - (optional) indexing jobs
- **kibana** - (optional) visualization for elasticsearch

**Persistent volumes:**

- Configuration (`etc_slurm`)
- Logs (`var_log_slurm`)
- Job files (`slurm_jobdir`)
- Database (`var_lib_mysql`)
- Authentication (`etc_munge`)

## 🖥️ Using the Cluster

```bash
# Access controller
make shell

# Inside controller:
sinfo                          # View cluster status
sbatch --wrap="hostname"       # Submit job
squeue                         # View queue
sacct                          # View accounting

# Or run example jobs
make run-examples
```

## 📈 Scaling

Compute nodes use Slurm's dynamic registration (`slurmd -Z`) and self-register
with sequential hostnames (c1, c2, c3... for CPU). Scale up
or down at any time without rebuilding.

### Scale CPU Workers

```bash
# Scale to 5 CPU workers (default is 2)
make scale-cpu-workers N=5

# Or set the default count in .env
CPU_WORKER_COUNT=4
make up
```

## 📊 Monitoring

### REST API

Query cluster via REST API (version auto-detected: v0.0.44 for 25.11.x, v0.0.42 for 25.05.x):

```bash
# Get JWT Token
JWT_TOKEN=$(docker exec slurmctld scontrol token 2>&1 | grep "SLURM_JWT=" | cut -d'=' -f2)

# Get nodes
docker exec slurmrestd curl -s -H "X-SLURM-USER-TOKEN: $JWT_TOKEN" \
  http://localhost:6820/slurm/v0.0.42/nodes | jq .nodes

# Get partitions
docker exec slurmrestd curl -s -H "X-SLURM-USER-TOKEN: $JWT_TOKEN" \
  http://localhost:6820/slurm/v0.0.42/partitions | jq .partitions
```

### Elasticsearch and Kibana (Optional)

Enable job completion monitoring and visualization:

```bash
# 1. Setting ELASTICSEARCH_HOST in .env enables the monitoring profile
ELASTICSEARCH_HOST=http://elasticsearch:9200

# 2. Start cluster (monitoring auto-enabled)
make up

# 3. Access Kibana at http://localhost:5601
# After loading, click: Elasticsearch → Index Management → slurm → Discover index

# 4. Query job completions directly
docker exec elasticsearch curl -s "http://localhost:9200/slurm/_search?pretty"

# Test monitoring
make test-monitoring
```

**Indexed data:** Job ID, user, partition, state, times, nodes, exit code

## 📦 Software Installation

[Spack](https://spack.io) is included in the image and integrates with [Lmod](https://lmod.readthedocs.io) so installed packages appear immediately as modules. All nodes share the same Spack and module tree.

```bash
make shell

spack install python@3.14
module avail
module load python/3.14.0
python --version
```

Modules are also available in batch jobs without any extra setup:

```bash
sbatch --wrap="module load python/3.14.0 && python3 --version"
```

To add a custom modulefile outside of Spack, drop a `.lua` file into the `opt_modulefiles` volume — it appears immediately on all nodes without a restart:

```bash
docker exec slurmctld mkdir -p /opt/modulefiles/myapp
docker cp myapp/1.0.lua slurmctld:/opt/modulefiles/myapp/1.0.lua
module avail
```

## 🔄 Cluster Management

Run `make` to see all available commands. Common ones:

```bash
make down     # Stop cluster (keeps data)
make clean    # Remove all containers and volumes
make rebuild  # Clean, rebuild, and restart
make logs     # View container logs
```

## 🐳 Docker Hub

Pre-built multi-arch images (amd64 + arm64) are published on each [GitHub release](https://github.com/giovtorres/slurm-docker-cluster/releases):

```bash
# CPU images
docker pull giovtorres/slurm-docker-cluster:latest
docker pull giovtorres/slurm-docker-cluster:25.11.4          # latest build for this Slurm version
docker pull giovtorres/slurm-docker-cluster:25.11.4-2.1.0   # pinned to a specific release
```

## ⚙️ Advanced

### Version Management

```bash
make set-version VER=25.11.4   # Switch Slurm version
make version                   # Show current version
make build-all                 # Build all supported versions
make test-all                  # Test all versions
```

### Configuration Updates

```bash
# Live edit (persists across restarts)
docker exec -it slurmctld vi /etc/slurm/slurm.conf
make reload-slurm

# Push local changes
vi config/25.11/slurm.conf
make update-slurm FILES="slurm.conf"

# Permanent changes
make rebuild
```

### Multi-Architecture Builds

```bash
# Cross-platform build (uses QEMU emulation)
docker buildx build --platform linux/arm64 \
  --build-arg SLURM_VERSION=25.11.4 \
  --load -t slurm-docker-cluster:25.11.4 .
```

## 📚 Documentation

- **Commands:** Run `make help` for all available commands
- **Examples:** Job scripts in `examples/` directory

## 🤝 Contributing

Contributions are welcomed! Fork this repo, create a branch, and submit a pull request.

## 📄 License

This project is licensed under the [MIT License](LICENSE).
