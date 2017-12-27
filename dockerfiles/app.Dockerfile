FROM golang:1.9-stretch AS backend_build

RUN mkdir -p /go/src/github.com/yaptide/app && \
  mkdir -p /build && \
  go get -u github.com/golang/dep/cmd/dep

COPY ./app /go/src/github.com/yaptide/app

RUN cd /go/src/github.com/yaptide/app && \
    rm -rf vendodor && \
    dep ensure && \
    go build -i -o /build/yaptide_backend
  
FROM debian:9
COPY --from=backend_build /build /root/backend

ENTRYPOINT /root/backend/yaptide_backend
