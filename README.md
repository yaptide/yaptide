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

With the `storage` compose profile, new result pages go to the Garage bucket and Postgres keeps where they are.
Pages stored before stay in Postgres; to move them (commands run in the `yaptide_flask` container):

1. Back up first: `scripts/backup.sh` (below), or at least a `pg_dump --format=custom`.
2. Copy: `docker exec yaptide_flask python -m yaptide.admin.db_manage copy-pages-to-storage`. It only reads the
   database: each page is uploaded to the key new pages use and checked there (size and MD5). Safe to stop and
   to repeat; a repeat uploads only what is missing.
3. Verify: `clear-pages-in-postgres --dry-run` lists any page without a matching copy.
4. Later, optionally: `clear-pages-in-postgres` removes the copied pages from Postgres, a batch per transaction,
   and only batches whose every page is verified in storage. From then on they are read from the bucket.

Back: `move-pages-to-postgres` writes every page kept in the bucket back into Postgres. Run it before downgrading
below migration `c75a1d0e4f21`, which refuses while any page lives only in the bucket. All commands take
`--dry-run` and `--batch-size`.

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

Restore (also on a new server, after `docker compose --profile storage up -d postgresql garage`):

```
docker compose stop nginx yaptide_flask yaptide_events yaptide_simulation_worker
scripts/backup.sh restore 2026-10-17     # pg_restore of that dump, then the pages copied back into Garage
docker compose --profile storage up -d
```

## For developers

For the git blame configuration to work correctly, it is necessary to set the following configuration:

```bash
git config blame.ignoreRevsFile .git-blame-ignore-revs
```


## Credits

This work was partially funded by EuroHPC PL Project, Smart Growth Operational Programme 4.2
