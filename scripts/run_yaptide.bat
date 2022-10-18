FOR %%A IN ("%~dp0.") DO SET folder=%%~dpA
echo %folder%

set SHIELDHIT_PATH=shieldhit
docker volume prune --force
docker-compose up -d --build
docker exec -w /usr/local/app/yaptide/data yaptide_flask python3 db_script.py
py .\yaptide\examples\call_api_example.py