# example .env file for Slurm, more options and comments can be found in slurm/.env.example
# copy these values to .env if using Slurm

# Docker Compose project name (affects container and volume name prefixes)
LMOD_VERSION=9.1.2
SPACK_VERSION=v1.1.1
MYSQL_USER=slurm
MYSQL_PASSWORD=password
MYSQL_DATABASE=slurm_acct_db
# SSH is required for yaptide-slurm communication
SSH_ENABLE=true
SSH_AUTHORIZED_KEYS=$HOME/.ssh/authorized_keys
SSH_PORT=3022

CPU_WORKER_COUNT=2

# Elasticsearch for job completion logging (OPTIONAL)
# Uncomment and set to enable monitoring with Elasticsearch/Kibana
# Leave commented for default file-based job completion logging
#ELASTICSEARCH_HOST=http://elasticsearch:9200
