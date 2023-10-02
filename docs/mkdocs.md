# Developer documentation

The documentation indended for developes is located in the `docs` folder. 
We use [mkdocs](https://www.mkdocs.org) with [material for mkdocs](https://squidfunk.github.io/mkdocs-material/) customisation to generate the documentation in the HTML format.

## Documentation structure

Technical documentation is written in markdown format and can be found in the [docs folder](https://github.com/yaptide/yaptide/tree/master/docs).

### API reference

The API reference is generated from the swagger yaml file. The swagger yaml file is located in the `docs` folder.

The documentation is rendered using [render_swagger](https://github.com/bharel/mkdocs-render-swagger-plugin) plugin installed as [mkdocs-render-swagger-plugin](https://pypi.org/project/mkdocs-render-swagger-plugin/) pip package. Its a bit abandoned project but it seems to be the only solution to generate static HTML from swagger yaml file.

As the swagger yaml file is located in the `docs` folder, the `mkdocs.yml` file needs to be located in the root of the project. This is a bit inconvenient as the `mkdocs.yml` file is not located in the `docs` folder.

## Github Pages deployment of the documentation

## Local deployment of the documentation

### Prerequisites

First a local venv environment needs to be created. This can be done by running the following command in the root of the project:

```bash
python3 -m venv venv
```

Activate the venv environment by running the following command:

```bash
source venv/bin/activate
```

For Windows (Powershell) use
```bash
. .\venv\Scripts\Activate.ps1
```

Then install the required packages needed by mkdocs by running the following command:

```bash
pip install -r requirements-docs.txt
```

### Building the documentation

To build the documentation run the following command:

```bash
mkdocs build
```

this will generate the documentation in the `site` folder.

To serve the documentation locally run the following command:

```bash
mkdocs serve
```

This will start a local webserver on port 8000. The documentation can be viewed by opening the following url in a browser: http://localhost:8000