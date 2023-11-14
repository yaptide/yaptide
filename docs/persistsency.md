# Persistency storage

Production version is using Postgresql database, while in tests we use SQLite.

To check database URI:

```
docker exec -it yaptide_flask bash -c "cd /usr/local/app && python -c 'from yaptide.application import create_app; app = create_app(); app.app_context().push() or print(app.extensions[\"sqlalchemy\"].engine.url.render_as_string(hide_password=False))'"
```

or

```
(venv) grzanka@grzankax1:~/workspace/yaptide$ DB_URL=$(docker exec -it yaptide_flask bash -c "cd /usr/local/app && python -c 'from yaptide.application import create_
app; app = create_app(); app.app_context().push() or print(app.extensions[\"sqlalchemy\"].engine.url.render_as_string(hide_password=False))'")
(venv) grzanka@grzankax1:~/workspace/yaptide$ echo $DB_URL
postgresql://yaptide_user:yaptide_password@postgresql:5432/yaptide_db
```

testing:
```
FLASK_SQLALCHEMY_DATABASE_URI=postgresql://yaptide_user:yaptide_password@localhost:5432/yaptide_db ./yaptide/admin/db_manage.py list-users
```
