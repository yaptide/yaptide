FROM python:3.9-alpine
ARG SHIELDHIT_PATH
COPY $SHIELDHIT_PATH /usr/local/bin/
WORKDIR /usr/local/app
COPY requirements.txt ./
RUN apk add gcc musl-dev build-base && \
    pip install -r requirements.txt && \
    apk del gcc musl-dev build-base
COPY yaptide ./yaptide
ENV FLASK_APP=yaptide.application
CMD ["flask", "run", "--host=0.0.0.0"]
