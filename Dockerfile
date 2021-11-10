FROM python:3.9-slim
ARG SHIELDHIT_PATH
COPY $SHIELDHIT_PATH /usr/local/bin/
WORKDIR /usr/local/app

# install dependencies
COPY ./requirements.txt ./
RUN pip install -r requirements.txt

# copy project
COPY yaptide ./yaptide