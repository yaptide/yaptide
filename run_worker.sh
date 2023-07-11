#!/bin/bash

./yaptide/admin/simulators.py install --name shieldhit

celery --app yaptide.celery.worker worker -E --loglevel=info -P eventlet --hostname yaptide-worker