"""Generate the code reference pages and navigation."""

from pathlib import Path

import mkdocs_gen_files

nav = mkdocs_gen_files.Nav()

for path in sorted(Path("yaptide").rglob("*.py")):
    module_path = path.relative_to("yaptide").with_suffix("")
    doc_path = path.relative_to("yaptide").with_suffix(".md")
    full_doc_path = Path("reference", doc_path)

    parts = tuple(module_path.parts)

    if parts[-1] == "__init__" or parts[-1] == "cli":
        continue

    nav[parts] = doc_path.as_posix()

    with mkdocs_gen_files.open(full_doc_path, "w") as fd:
        ident = ".".join(parts)
        fd.write(f"::: {ident}")

    mkdocs_gen_files.set_edit_path(full_doc_path, path)

with mkdocs_gen_files.open("reference/SUMMARY.md", "w") as nav_file:
    nav_file.writelines(nav.build_literate_nav())

# copy the openapi.yaml file from the flask_static directory to the docs directory
flask_static_openapi_path = Path('yaptide', 'static', 'openapi.yaml')
mkdocs_openapi_path = Path('docs', 'openapi.yaml')
mkdocs_openapi_path.write_text(flask_static_openapi_path.read_text())
