# Developer documentation

The documentation indended for developes is located in the `docs` folder.
We use [mkdocs](https://www.mkdocs.org) with [material for mkdocs](https://squidfunk.github.io/mkdocs-material/) customisation to generate the documentation in the HTML format.

## Documentation structure

### Technical documentation

Technical documentation is written in markdown format and can be found in the [docs folder](https://github.com/yaptide/yaptide/tree/master/docs).

### API reference

The [API reference](swagger.md) is generated from the [swagger](https://swagger.io) yaml file.
The [swagger.yaml](https://github.com/yaptide/yaptide/blob/master/yaptide/static/openapi.yaml) file is located in the [yaptide/static](https://github.com/yaptide/yaptide/tree/master/yaptide/static) folder. This is the location from which Flask serve it when the backend is deployed.

The HTML API documentation is rendered using [render_swagger](https://github.com/bharel/mkdocs-render-swagger-plugin) mkdocs plugin installed as [mkdocs-render-swagger-plugin](https://pypi.org/project/mkdocs-render-swagger-plugin/) pip package.
Its a bit abandoned project but it seems to be the only solution to generate static HTML from swagger yaml file.
The swagger documenation can be viewed locally by deploying backend and connecting to the backend server via `/api/docs` endpoint.
By using the `mkdocs-render-swagger-plugin` we can serve the documenation statically on github pages.
This way users may read the documenation without deploying the backend.

The `mkdocs-render-swagger-plugin` expects the swagger yaml file to be located in the  [docs folder](https://github.com/yaptide/yaptide/tree/master/docs). Therefore we modified the [docs/gen_ref_pages.py](https://github.com/yaptide/yaptide/blob/master/docs/gen_ref_pages.py) script to copy the swagger yaml file from the Flask static directory to the docs folder. The copy happens whenever the `mkdocs build` or `mkdocs serve` command is run.

### Code reference

The code reference is generated using [mkdocs-gen-files](https://github.com/oprypin/mkdocs-gen-files) mkdocs plugin.
We have a [docs/gen_ref_pages.py](https://github.com/yaptide/yaptide/blob/master/docs/gen_ref_pages.py) scripts that crawls through all Python files in the [yaptide  folder](https://github.com/yaptide/yaptide/tree/master/yaptide) directory. Then it generates on-the-fly a markdown documentation from docstrings for each module, class and function. Also a on-the-fly `reference/SUMMARY.md` file is generated using [mkdocs-literate-nav](https://github.com/oprypin/mkdocs-literate-nav) mkdocs plugin. This file serves as left-side menu for the code reference.

### Tests coverage

The tests coverage is generated using [mkdocs-coverage](https://github.com/pawamoy/mkdocs-coverage) mkdocs plugin. This plugin expects a pytest coverage report in the `htmlcov` directory.

## Github Pages deployment of the documentation

Github pages deployment is done using [GitHub Actions docs workflow](https://github.com/yaptide/yaptide/blob/master/.github/workflows/docs.yml).
It deploys new version of the documentation whenever a new commit is pushed to the `master` branch.
The deployment includes generation of test coverage report and API reference documentation.

## Local deployment of the documentation

### Prerequisites

First, user needs to install [poetry](https://python-poetry.org).
Then, user needs to install the dependencies for the backend and the documentation:

```bash
poetry install --only main,docs
```

### Building the documentation

To build the documentation run the following command:

```bash
poetry run mkdocs build
```

this will generate the documentation in the `site` folder.

To serve the documentation locally run the following command:

```bash
poetry run mkdocs serve
```

This will start a local webserver on port 8000. The documentation can be viewed by opening the following url in a browser: http://localhost:8000

### Working with the technical documentation

After modification of the markdown file the documenation served via `mkdocs serve` command will be updated automatically.

### Working with the API reference

After modification of the swagger yaml one needs to stop the `mkdocs serve` command and run it again. This is required as to re-generate the API reference documentation mkdocs needs to copy the swagger yaml file from the Flask static directory to the docs folder.
Please avoid modification and commiting of the swagger yaml file in the docs folder as it will be overwritten by the `mkdocs serve` command.

### Working with the code reference

After modification of the Python code one needs to stop the `mkdocs serve` command and run it again.

### Working with the tests coverage

To regeneate tests coverage one needs to run the following command:

```bash
poetry run pytest --cov-report html:htmlcov --cov=yaptide
```

Note that this requires installation of dependencies for the backend and the tests:

```bash
poetry install --only main,test
```
