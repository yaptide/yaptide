FROM node:8 AS frontend

ARG YAPTIDE_BACKEND_PUBLIC_URL
ARG YAPTIDE_FRONTEND_PUBLIC_URL
ARG YAPTIDE_FRONTEND_PORT

COPY ./ui /root/app
RUN cd /root/app && \
  npm install && \
  npm run deploy

RUN mv /root/app/static /build


FROM golang:1.9-stretch AS backend

RUN mkdir -p /go/src/github.com/yaptide/yaptide && \
  mkdir -p /build && \
  go get -u github.com/golang/dep/cmd/dep

COPY ./app /go/src/github.com/yaptide/yaptide

RUN cd /go/src/github.com/yaptide/yaptide && \
    dep ensure && \
    go build -i -o /build/yaptide


FROM debian:9

RUN DEBIAN_FRONTEND=noninteractive apt-get -y update && \
  DEBIAN_FRONTEND=noninteractive apt-get -y install nginx

COPY --from=frontend /build /root/frontend
COPY --from=backend /build /root/backend
COPY ./builder/config/frontend.nginx.conf /etc/nginx/nginx.conf

ENTRYPOINT (nginx -c /etc/nginx/nginx.conf ; /root/backend/yaptide_backend) &
