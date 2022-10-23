docker stop yaptide_flask
docker stop yaptide_worker
docker stop yaptide_redis

docker rm yaptide_flask
docker rm yaptide_worker
docker rm yaptide_redis

docker rmi yaptide_flask
docker rmi yaptide_worker