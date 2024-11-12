docker stop yaptide_flask
docker stop yaptide_simulation_worker
docker stop yaptide_helper_worker
docker stop yaptide_redis
docker stop yaptide_flower
docker stop yaptide_nginx

docker rm yaptide_flask
docker rm yaptide_simulation_worker
docker rm yaptide_helper_worker
docker rm yaptide_redis
docker rm yaptide_flower
docker rm yaptide_nginx

docker rmi yaptide_flask
docker rmi yaptide_simulation_worker
docker rmi yaptide_helper_worker
docker rmi yaptide_nginx
