# yaptide backend

## User documentation
 - [User documentation](https://yaptide.github.io/docs/)


## Getting the code

Clone the repository:

```shell
git clone https://github.com/yaptide/yaptide.git
```

## Building and running the app

There are two main ways of build and run the app
- [For developers](https://yaptide.github.io/for_developers/backend/for_developers/), which is setting up all components manually. It is faster then Docker.
- [Using Docker](https://yaptide.github.io/for_developers/backend/using_docker/). Used for the deployment, takes more time.

## Result pages in object storage

Result pages are kept in the Garage bucket (compose service `garage`), and Postgres keeps only where each page is.
Garage needs three values in `.env` before the first start, and they stay fixed afterwards: a new secret for the same
key id stops Garage from starting.

| Variable | |
|---|---|
| `RESULTS_S3_ACCESS_KEY` | `GK` followed by 24 hex bytes, e.g. `echo GK$(openssl rand -hex 12)` |
| `RESULTS_S3_SECRET_KEY` | 32 hex bytes, `openssl rand -hex 32` |
| `GARAGE_RPC_SECRET` | 32 hex bytes, `openssl rand -hex 32` |

The browser reads a page through nginx (`/yaptide-results/`) with signed links that `/results` hands out, so
`BACKEND_EXTERNAL_URL` has to be the address the browser reaches nginx at.

Pages stored before this version stay in Postgres and are still served from there. To move them (commands run in
the `yaptide_flask` container):

1. Back up first: `scripts/backup.sh` (below), or at least a `pg_dump --format=custom`.
2. Copy: `docker exec yaptide_flask python -m yaptide.admin.db_manage copy-pages-to-storage`. It only reads the
   database: each page is converted to Zarr, as new pages are, uploaded and checked there (size and MD5). Safe to
   stop and to repeat; a repeat uploads only what is missing. Pages of unfinished simulations are left (the backend
   may still replace them); repeat after they end.
3. Verify: `clear-pages-in-postgres --dry-run` lists any page without a matching copy.
4. Then `clear-pages-in-postgres` removes the copied pages from Postgres, a batch per transaction, and only batches
   whose every page is verified in storage. From then on they are read from the bucket.

Back: `move-pages-to-postgres` writes every page kept in the bucket back into Postgres, converted back to JSON (the
values keep float32 precision). Run it before downgrading below migration `9e2b41c7d5a3`, which refuses while any
page lives only in the bucket. All commands take `--dry-run` and `--batch-size`.

## Backups

`scripts/backup.sh`, run on the host from the repository directory, sends a `pg_dump` (custom format) and a mirror
of the result pages to a second S3 server. It reads `.env`:

| Variable | |
|---|---|
| `BACKUP_S3_ENDPOINT` | address of the backup S3 server, e.g. `https://s3.example.org` |
| `BACKUP_S3_BUCKET` | bucket for the backups, created beforehand |
| `BACKUP_S3_ACCESS_KEY`, `BACKUP_S3_SECRET_KEY` | keys allowed to list, read, write and delete in it |
| `BACKUP_S3_REGION` | only if the server wants one |

In the bucket: `postgres/daily/DATE.dump` (kept 14 days), `postgres/weekly/DATE.dump` (Sundays, kept 8 weeks),
`results/` (the pages, mirrored at every run) and `replaced/DATE/` (pages removed or replaced in Garage since the
run before, kept 14 days). It needs only Docker (rclone runs from the pinned `rclone/rclone` image). `.env` itself
is not backed up: keep a copy elsewhere, a restored Garage needs the same keys. Nightly, e.g.:

```
30 2 * * * cd /path/to/yaptide && scripts/backup.sh >> /var/log/yaptide-backup.log 2>&1
```

Restore (also on a new server, after `docker compose up -d postgresql garage`):

```
docker compose stop nginx yaptide_flask yaptide_simulation_worker yaptide_helper_worker
scripts/backup.sh restore 2026-10-17     # pg_restore of that dump, then the missing pages copied back into Garage
docker compose up -d
```

The restore asks for the database name, and first saves the database it replaces to
`postgres/before-restore/` (kept), to undo it with `pg_restore --clean`. The nightly run stops, before removing any
backup, when the dump fails or when the bucket has less than half of the pages mirrored (a lost Garage).

## For developers

For the git blame configuration to work correctly, it is necessary to set the following configuration:

```bash
git config blame.ignoreRevsFile .git-blame-ignore-revs
```


## Credits

This work was partially funded by EuroHPC PL Project, Smart Growth Operational Programme 4.2
