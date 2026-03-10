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
`local-dev/ssh-ca/ca.pub` (public, safe to commit).

> **Skip** this step on subsequent runs — the script exits early if the key already exists.

### Step 2 — Build and start the stack

```bash
docker compose -f local-dev/docker-compose-local-slurm.yml up --build
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
