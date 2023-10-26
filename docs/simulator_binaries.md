# How to download simulators binaries from S3 via command line

Currently, we store binaries of three simulators on S3 platform. SHIELD-HIT12A (full version) and Fluka files are encrypted.

To simply init download process we have to run following commands:

```bash
./yaptide/admin/simulators.py install --name simulator_name --path path_to_download
```

To get full instruction of command usage we can type
```bash
./yaptide/admin/simulators.py install --help
```
