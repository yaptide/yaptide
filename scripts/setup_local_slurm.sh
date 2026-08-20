#!/bin/bash
set -e

FLASK_SQLALCHEMY_DATABASE_URI="sqlite:///instance/db.sqlite" poetry run yaptide/admin/db_manage.py add-cluster localhost -p 3022
