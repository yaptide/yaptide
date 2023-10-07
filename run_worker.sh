#!/bin/bash

./yaptide/admin/simulators.py install --name shieldhit
./yaptide/admin/simulators.py install --name topas

celery --app yaptide.celery.worker worker -E --loglevel=info -P eventlet --hostname yaptide-worker