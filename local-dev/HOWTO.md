# Local SLURM Development Environment — How-To

This setup reproduces the production **C3 Cloud → Ares cluster** flow locally using Docker
Compose. It lets you test batch SLURM job submission end-to-end without access to PLGrid
infrastructure.

## Architecture

```
Browser (React UI)
  │
  └─► Keycloak (localhost:8080)  ─── SSO replacing sso.plgrid.pl
          │  token
          ▼
      Flask (localhost:5000)
          │  CERT_AUTH_URL
          ├─► cert-issuer (localhost:8001)  ─── SSH cert issuer replacing ccm-dev.kdm.cyfronet.pl
          │
          │  POST /jobs/batch
          ▼
      Celery helper worker
          │  SSH (cert-based)
          ▼
      SLURM container (localhost:2222)
          ├─ sbatch → array jobs → shieldhit demo binary
          └─ collect job → convertmc (pymchelper) → POST http://nginx:5000/results
```

## Prerequisites

- Docker Desktop (or Docker Engine + Compose plugin) ≥ 24
- `docker compose` version ≥ 2.20 (needed for the `include:` directive)
- Internet access at **build time** — the SLURM container downloads the
  [SHIELD-HIT12A demo binary](https://shieldhit.org) from shieldhit.org automatically

## Quick Start

### Step 1 — Generate SSH CA key pair (once)

```bash
bash local-dev/generate_ssh_ca.sh
```

This creates `local-dev/ssh-ca/ca_key` (private, never commit) and
`local-dev/ssh-ca/ca_key.pub` (public, safe to commit).

> **Skip** this step on subsequent runs — the script exits early if the key already exists.

### Step 2 — Build and start the stack

```bash
docker compose -f local-dev/docker-compose-local-slurm.yml up --build -d
```

During the build the SLURM container:
- downloads the SHIELD-HIT12A v1.1.0 demo binary from `shieldhit.org`
- installs `pymchelper==2.8.5` (provides the real `convertmc` CLI)

First build takes a few extra minutes because of the downloads. Subsequent builds are
cached.

> **Keycloak takes ~60 seconds to start.** Wait until `docker ps` shows `(healthy)` for
> `yaptide_keycloak` before running Step 3.
> You can watch it with: `docker inspect --format '{{.State.Health.Status}}' yaptide_keycloak`
>
> Verify Keycloak is ready from the host:
> ```bash
> curl http://localhost:8080/auth/realms/yaptide-local
> # expected: JSON with "realm":"yaptide-local"
> ```

### Step 3 — Register the SLURM cluster (once)

```bash
bash local-dev/setup_local_cluster.sh
```

This calls `db_manage.py add-cluster slurm` inside the Flask container. Only needed once;
the database is persisted in the `postgres_data` volume.

If the cluster is already registered (e.g. from a previous run) you will see
`Cluster slurm already exists in DB` — that is fine, no action needed.

### Step 4 — Start the React UI

```bash
cd ../ui
REACT_APP_KEYCLOAK_BASE_URL=http://localhost:8080 \
REACT_APP_KEYCLOAK_REALM=yaptide-local \
REACT_APP_KEYCLOAK_CLIENT_ID=yaptide-client \
REACT_APP_ALT_AUTH=plg \
REACT_APP_BACKEND_URL=http://localhost:5000 \
npm start
```

Log in with the pre-configured test user: **username** `testuser`, **password** `Testpass1!`.

---

## Optional: Run Flask Locally Via Poetry

If you want to work on the Flask backend without rebuilding the `yaptide_flask` image,
you can run Flask on the host via Poetry and keep the rest of the local SLURM stack in Docker.

This setup is supported for:
- Flask on the host
- PostgreSQL, Redis, Keycloak, cert-issuer, SLURM and helper worker in Docker

It is intended to work on:
- macOS with Docker Desktop
- Linux with Docker Engine / Docker Desktop

This setup is **not** recommended for running the batch helper worker on the host.
`batch_methods.get_connection()` connects to the cluster using `cluster.cluster_name`, which
works inside the Docker network (`slurm:22`) but does not naturally map to the host-exposed
port (`localhost:2222`).

For this workflow, use the dedicated Compose service
`yaptide_helper_worker_external_flask`. It depends only on Redis and reaches the host Flask
process purely through environment variables, so it does not pull in the dockerized
`yaptide_flask` service.

### Step A — Start only the supporting services in Docker

Stop the full stack first if it is already running:

```bash
docker compose -f local-dev/docker-compose-local-slurm.yml down
```

Then start only the services that Flask depends on, plus the helper and simulation workers:

```bash
BACKEND_INTERNAL_URL=http://host.docker.internal:5001 \
BACKEND_EXTERNAL_URL=http://host.docker.internal:5001 \
docker compose --profile external-flask -f local-dev/docker-compose-local-slurm.yml up -d \
   postgresql redis keycloak cert-issuer slurm \
   yaptide_helper_worker_external_flask \
   yaptide_simulation_worker_external_flask
```

Why both backend URLs point to `host.docker.internal`:
- `BACKEND_INTERNAL_URL` is used by the helper and simulation workers to call `/jobs` and POST task status updates
- `BACKEND_EXTERNAL_URL` is embedded into the SLURM scripts and later used by the collect
   phase to call `/results`

`yaptide_simulation_worker_external_flask` handles **direct-run** simulations (the `simulations`
Celery queue). Without it, direct-run jobs would stay in `PENDING` indefinitely because no
worker is consuming the queue.

In this repository, `docker-compose-local-slurm.yml` adds an explicit `extra_hosts` mapping for
`host.docker.internal`, so the same hostname works for this workflow on both macOS and Linux.



If the cluster is already registered (e.g. from a previous all-Docker run) you will see
`Cluster slurm already exists in DB` — that is fine, no action needed.

### Step C — Configure SSH for the local SLURM container

Flask on the host connects to the SLURM container via SSH using `cluster.cluster_name` as
the hostname. That hostname (`slurm`) resolves only inside the Docker network. Add an SSH
config entry so the host can reach it via the exposed port 2222:

```bash
cat >> ~/.ssh/config << 'EOF'

# yaptide local-dev: map Docker SLURM hostname to localhost:2222
Host slurm
    HostName 127.0.0.1
    Port 2222
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
EOF
```

> **Skip** this step on subsequent runs — SSH config is persistent.
> If the entry already exists, adding a duplicate is harmless but can be removed manually.

### Step C — Run Flask locally with Poetry

From the `yaptide/` directory:

```bash
export FLASK_APP=yaptide.application
export FLASK_USE_CORS=true
export FLASK_SQLALCHEMY_DATABASE_URI='postgresql+psycopg://yaptide_user:yaptide_password@localhost:5432/yaptide_db'
export CELERY_BROKER_URL='redis://localhost:6379/0'
export CELERY_RESULT_BACKEND='redis://localhost:6379/0'
export CERT_AUTH_URL='http://localhost:8001/key'
export KEYCLOAK_BASE_URL='http://localhost:8080'
export KEYCLOAK_REALM='yaptide-local'
export BACKEND_EXTERNAL_URL='http://host.docker.internal:5001'
export CLUSTER_SSH_ADDR='127.0.0.1:2222'

poetry run flask run --host 0.0.0.0 --port 5001
```


### Step D — Register the SLURM cluster (once)

The SLURM cluster must be registered in the database. In external-Flask mode the
`yaptide_flask` container does not exist, so run `db_manage.py` via Poetry on the host.

> **Flask must already be running (Step C) before this step**, because Flask creates the
> database tables on startup. Run this in a separate terminal after Step D.

```bash
bash local-dev/setup_local_cluster.sh --external-flask
```
### Step E — Point the React UI at the host Flask process

```bash
cd ../ui
HOST=127.0.0.1 \
REACT_APP_KEYCLOAK_BASE_URL=http://localhost:8080 \
REACT_APP_KEYCLOAK_REALM=yaptide-local \
REACT_APP_KEYCLOAK_CLIENT_ID=yaptide-client \
REACT_APP_ALT_AUTH=plg \
REACT_APP_BACKEND_URL=http://127.0.0.1:5001 \
npm start
```

Open the UI at **`http://127.0.0.1:3000`** (not `localhost:3000`).

`HOST=127.0.0.1` is required so that the React dev server binds to `127.0.0.1` and the
browser opens the page from the same hostname as the Flask backend. If the page is served
from `localhost:3000` while the Flask backend is on `127.0.0.1:5001`, browsers treat them
as cross-site and reject the `access_token` cookie (SameSite=Lax).

> **If Keycloak is already running** with a realm imported before this change, you need to
> add `http://127.0.0.1:3000/*` to the client's Valid Redirect URIs manually in the
> Keycloak admin console at `http://localhost:8080/auth/admin`, or restart the Keycloak
> container so the updated `realm-export.json` is re-imported:
> ```bash
> docker compose -f local-dev/docker-compose-local-slurm.yml restart keycloak
> ```

### Notes

- In this mode, Flask logs come from your local terminal, not `docker logs yaptide_flask`.
- Batch jobs still run through `yaptide_helper_worker_external_flask` and the SLURM container in Docker.
- If your Docker version does not support `host-gateway`, this host-Flask workflow will need a
   manual host IP instead of `host.docker.internal`.
- If you want to return to the default all-Docker setup, stop the local Flask process and run:

```bash
docker compose -f local-dev/docker-compose-local-slurm.yml up --build -d
```

---


## Simulator availability in the SLURM container

The SLURM container uses the **real** SHIELD-HIT12A demo binary, not a mock.

| Tool | Source | Notes |
|---|---|---|
| `shieldhit` | Downloaded from shieldhit.org at build time | Demo v1.1.0 — limited primaries per run |
| `convertmc` | `pymchelper==2.8.5` installed via pip | Real converter, JSON format matches backend |
| `module` | No-op stub | Templates call `module load shieldhit`; Lmod is not installed |
| `sacct` | Thin squeue/scontrol wrapper | SLURM accounting daemon not enabled locally |

The demo version of SHIELD-HIT12A supports the full input format produced by yaptide. The
only limitation is a cap on the number of primaries per simulation run.


---

## End-to-end verification checklist

After all services are running and the cluster is registered:

1. **Keycloak realm** — returns 200 from the host:
   ```bash
   curl http://localhost:8080/auth/realms/yaptide-local
   # expected: JSON with "realm":"yaptide-local"
   ```
2. **SLURM is idle** — node shows `idle`, no jobs in queue:
   ```bash
   docker exec yaptide_slurm sinfo
   docker exec yaptide_slurm squeue
   ```
3. **cert-issuer** — Swagger UI responds:
   ```bash
   curl -s http://localhost:8001/docs | grep -q 'swagger' && echo OK
   ```
4. **SLURM SSH port** — reachable (auth failure expected without a cert, not connection refused):
   ```bash
   ssh -o BatchMode=yes -o ConnectTimeout=5 -p 2222 testuser@localhost echo hi
   # expected: "Permission denied (publickey)" — port is open, auth works correctly
   ```
5. **UI login** — `npm start` in `ui/`, log in as `testuser` / `Testpass1!`
6. **Submit a batch job** — choose *PLGrid/SLURM* backend in the UI, submit a simulation
7. **Watch progress** — job state should go `PENDING → RUNNING → COMPLETED` in the UI
8. **Check SLURM logs** inside the container:
   ```bash
   docker exec yaptide_slurm cat /var/log/slurm/slurmctld.log
   docker exec yaptide_slurm squeue
   ```
9. **Inspect Flask logs**:
   ```bash
   docker logs yaptide_flask -f
   ```

---

## Stopping and cleaning up

```bash
# Stop containers (keep volumes)
docker compose -f local-dev/docker-compose-local-slurm.yml down

# Stop and remove all volumes (wipes the database)
docker compose -f local-dev/docker-compose-local-slurm.yml down -v
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ssh: no supported authentication methods` | SSH CA key not mounted | Run `generate_ssh_ca.sh` first, then rebuild |
| Keycloak shows `unhealthy` | Keycloak version incompatibility with healthcheck | Already fixed; rebuild with `--no-cache` if you have an old image |
| Keycloak login loop / `realm not found` | Keycloak still starting | Wait for `(healthy)`; `docker logs yaptide_keycloak` |
| `Cluster slurm already exists in DB` | Step 3 already done (volumes persist) | Normal — the cluster is registered, no action needed |
| `cluster not found` in Flask | Step 3 not done | Run `setup_local_cluster.sh` |
| `shieldhit: not found` in SLURM logs | Build failed during download | Check internet access; rebuild with `--no-cache` |
| `convertmc: not found` | pip install failed | Rebuild; check Docker build output for pip errors |
| Job stuck in `PENDING` | SLURM node drained | `docker exec yaptide_slurm scontrol update node=slurm state=resume` |
