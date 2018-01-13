FROM golang:1.9-stretch AS backend_build

RUN mkdir -p /go/src/github.com/yaptide/app && \
  mkdir -p /build && \
  go get -u github.com/golang/dep/cmd/dep

RUN wget https://neptun.phys.au.dk/~bassler/SHIELD_HIT/DEMO/shield_hit12a_x86_64_demo_gfortran_v0.7.2.tar.gz && \
  tar -xf shield_hit12a_x86_64_demo_gfortran_v0.7.2.tar.gz && \
  cp shield_hit12a_x86_64_demo_gfortran_v0.7.2/bin/shieldhit /build/shieldhit

COPY . /go/src/github.com/yaptide/app

RUN cd /go/src/github.com/yaptide/app && \
    rm -rf vendodor && \
    dep ensure && \
    go build -i -o /build/yaptide_backend
  
FROM debian:9
COPY --from=backend_build /build /root/backend
COPY --from=backend_build /build/shieldhit /usr/bin/shieldhit

ENTRYPOINT /root/backend/yaptide_backend
