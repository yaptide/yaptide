export DOLLAR="$" && envsubst < /nginx.conf.template > /etc/nginx/conf.d/nginx.conf
nginx -g 'daemon off;'