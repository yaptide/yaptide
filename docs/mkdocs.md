# Developer documentation

The documentation indended for developes is located in the `docs` folder. 
We use mkdocs to generate the documentation in html format.


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