FROM python:3.9-slim
ARG SHIELDHIT_PATH
COPY $SHIELDHIT_PATH /usr/local/bin/
WORKDIR /usr/local/app

RUN apt-get -qq update && \
    apt-get install -qq -y --no-install-recommends gfortran && \
    rm -rf /var/lib/apt/lists/*

# install dependencies
COPY ./requirements.txt ./
RUN pip install -r requirements.txt

# copy project
COPY yaptide ./yaptide
