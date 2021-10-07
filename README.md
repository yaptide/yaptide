# Installation
Run: ```$ pip install -r requrements.txt```

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
docker run -dp 5000:5000 yaptide
```

Once it's running, the app will be available at [http://localhost:5000](http://localhost:5000).
