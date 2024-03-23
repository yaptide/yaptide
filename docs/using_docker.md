# Using Docker

You can build and run the app using the following command:

```shell
docker compose up -d --build
```

Once it's running, the app will be available at [http://localhost:5000](http://localhost:5000). If you get an error saying the container name is already in use, stop and remove the container and then try again.

When you're ready to stop the containers, use the following commands:

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
