We have 3 types of JSON files:

1. **Project JSON** - file that could be generated using UI and saved using "Save project" button
   - Examples of such files are in [this GitHub repository](https://github.com/yaptide/ui/tree/master/src/ThreeEditor/examples) or in `yaptide_tester/example.json`
   - This file can contain only simulation input in JSON format or results as well
   - Top-level keys: "metadata", "project", "scene", and others...

2. **Payload JSON** - object which is sent to the server using POST request from UI
   - All such objects contain "input_files" or "input_json" top-level key
     - a) **Editor Payload JSON** type assumes that the user defined the simulation using UI 3D Editor and selected it for running
       - Examples of such files are in `tests/res/json_payload_editor.json`
       - Inside "input_json" key, we have the contents of the project JSON file
     - b) **Files Payload JSON** type assumes that the user uploaded input files and selected them for running
       - Examples of such files are in `tests/res/json_payload_files.json`
       - Inside "input_files" key, we have a dictionary with filenames as keys and contents of input files as values

We assume the following conventions: `editor_dict`, `payload_editor_dict`, `payload_files_dict`, and `payload_dict`

- `editor_dict['metadata']`, `editor_dict['scene']` is always valid
- `editor_dict['input_type']` is not valid

`payload_dict` can be either `payload_editor_dict` or `payload_files_dict`
- `payload_dict['input_type']` is always valid

Therefore, `payload_editor_dict['input_json']` can be passed as `editor_dict`
- `payload_editor_dict['input_json']['metadata']` is valid
- `payload_editor_dict['input_json']['scene']` is valid
- `payload_editor_dict['input_json']['beam.dat']` is not valid
- `payload_editor_dict['input_files']['beam.dat']` is not valid

Therefore, for `payload_files_dict['input_files']`
- `payload_files_dict['input_files']['metadata']` is not valid
- `payload_files_dict['input_files']['beam.dat']` is valid
- `payload_editor_dict['input_json']['metadata']` is not valid

We also have `files_dict` where keys are filenames and values are contents of input files
- `files_dict[beam.dat]` is valid
