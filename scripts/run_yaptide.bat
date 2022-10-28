FOR %%A IN ("%~dp0.") DO SET folder=%%~dpA

set SHIELDHIT_PATH=%1
docker volume prune --force
docker-compose up -d --build
docker cp grid_proxy yaptide_flask:/usr/local/app
docker exec -w /usr/local/app/ yaptide_flask python3 yaptide/admin/db_manage.py add-user admin --password password --proxy grid_proxy
docker exec -w /usr/local/app/ yaptide_flask python3 yaptide/admin/db_manage.py list-users