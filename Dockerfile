FROM python:3.9-alpine
ARG SHIELDHIT_PATH
COPY $SHIELDHIT_PATH /usr/local/bin/
WORKDIR /usr/local/app

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# install dependencies
COPY ./requirements.txt ./
RUN apk add gcc musl-dev build-base && \
    pip install -r requirements.txt && \
    apk del gcc musl-dev build-base

# copy project
COPY yaptide ./yaptide