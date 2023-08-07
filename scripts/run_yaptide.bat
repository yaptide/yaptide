FOR %%A IN ("%~dp0.") DO SET folder=%%~dpA

docker volume prune --force
docker-compose up -d --build
docker exec -w /usr/local/app/ yaptide_flask python3 yaptide/admin/db_manage.py add-user admin --password password
docker exec -w /usr/local/app/ yaptide_flask python3 yaptide/admin/db_manage.py add-cluster ares.cyfronet.pl
docker exec -w /usr/local/app/ yaptide_flask python3 yaptide/admin/db_manage.py list-users
docker exec -w /usr/local/app/ yaptide_flask python3 yaptide/admin/db_manage.py list-clusters