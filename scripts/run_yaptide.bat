FOR %%A IN ("%~dp0.") DO SET folder=%%~dpA

set SHIELDHIT_PATH=%1
docker volume prune --force
docker-compose up -d --build
docker exec -w /usr/local/app/yaptide/data yaptide_flask python3 db_script.py