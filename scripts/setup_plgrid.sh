#!/bin/bash
docker exec yaptide_flask python3 yaptide/admin/db_manage.py add-cluster ares.cyfronet.pl
docker exec yaptide_flask python3 yaptide/admin/db_manage.py list-clusters