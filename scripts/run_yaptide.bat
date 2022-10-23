FOR %%A IN ("%~dp0.") DO SET folder=%%~dpA

set SHIELDHIT_PATH=shieldhit
docker volume prune --force
docker-compose up -d --build
docker exec -w /usr/local/app/yaptide/data yaptide_flask python3 db_script.py

py .\yaptide_local_tester\yaptide_tester.py

docker stop yaptide_flask
docker stop yaptide_worker
docker stop yaptide_redis

docker rm yaptide_flask
docker rm yaptide_worker
docker rm yaptide_redis

docker rmi yaptide_flask
docker rmi yaptide_worker