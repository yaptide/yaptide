FROM node:8 AS frontend_build

ARG YAPTIDE_BACKEND_PUBLIC_URL
ARG YAPTIDE_FRONTEND_PUBLIC_URL
ARG YAPTIDE_FRONTEND_PORT

COPY ./ui /root/app
RUN cd /root/app && \
  rm -rf node_modules && \
  npm install && \
  npm run deploy

RUN mv /root/app/static /build

FROM debian:9

RUN DEBIAN_FRONTEND=noninteractive apt-get -y update && \
  DEBIAN_FRONTEND=noninteractive apt-get -y install nginx

COPY --from=frontend_build /build /root/frontend
COPY ./builder/config/frontend.nginx.conf /etc/nginx/nginx.conf

ARG YAPTIDE_BACKEND_PUBLIC_URL
ARG YAPTIDE_FORNTEND_PUBLIC_URL
ARG YAPTIDE_FORNTEND_PORT

ENTRYPOINT nginx -c /etc/nginx/nginx.conf

