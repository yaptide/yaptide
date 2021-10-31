# Installation
Run: ```$ pip install -r requirements.txt```

# Running the app
1. Set FLASK_APP env variable ([explanation](https://flask.palletsprojects.com/en/2.0.x/cli/)):
   * Windows: ```$ set FLASK_APP=yaptide.application```
   * Linux: ```$ export FLASK_APP=yaptide.application```

2. Run the app: ```$ flask run```
   * By default the app will re-create the database with each run, dropping it in the process. 
   * To persist the database between runs this ```with app.app_context():
        models.create_models()``` in yaptide/application.py inside the ```create_app``` factory.

# Building/Running with Docker

You can build the app using the following command:

```shell
docker build -t yaptide .
```

Once built, you can run a container using the following command:

```shell
docker run -dp 5000:5000 --name=yaptide yaptide
```

Once it's running, the app will be available at [http://localhost:5000](http://localhost:5000). If you get an error saying the container name is already in use, stop and remove the container and then try again.

When you're ready to stop the container, use the following command:

```shell
docker stop yaptide
docker rm yaptide
```
