#!/bin/bash
docker cp server.key yaptide_nginx:/etc/nginx/conf.d/server.key
docker cp server.crt yaptide_nginx:/etc/nginx/conf.d/server.crt
docker restart yaptide_nginx
