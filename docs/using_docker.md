# Using Docker

You can build and run the app using docker compose. Docker deploy is similar to production deploy, so it's a good way to test the app.
To facilitate app development you can use following scripts to deploy app using docker containters:

=== "Linux"
    ```bash
    scripts/start_with_docker.sh
    ```

=== "Windows (PowerShell)"
    ```powershell
    scripts/start_with_docker.ps1
    ```

The script will build the app and run it in the background. The building is equivalent to running the following command:

```shell
docker compose up --build --detach
```

If you have docker engine v25 (released 2024-01-19) or newer the you can profit from fast starting time and use following command:

```shell
docker compose -f docker-compose.yml -f docker-compose.fast.yml up --build --detach
```

The script `scripts/start_with_docker.*` will use the fastest way to start the app.

Once it's running, the app will be available at [http://localhost:5000](http://localhost:5000). If you get an error saying the container name is already in use, stop and remove the container and then try again.

When you're ready to stop the containers, use the following command:

```shell
docker compose down
```

## Docker database

Now registering, updating and deleting users is available with the use of `db_manage.py` located in `yaptide/admin` folder.

Once docker compose is running, you can use the following command, to get more information:
```
docker exec -w /usr/local/app/ yaptide_flask ./yaptide/admin/db_manage.py --help
```

To add an user run:

```bash
docker exec -w /usr/local/app/ yaptide_flask ./yaptide/admin/db_manage.py add-user admin --password password
```
