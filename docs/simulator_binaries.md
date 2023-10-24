# How to download simulators binaries from S3 via Command Line

Currently, we store binaries of 3 simulators on S3 platform. Shielthit and Fluka files are encrypted.

To simply init download process we have to run following commands:
```bash
cd ../yaptide/admin
python3 simulators.py install --name [simulator name] --path [path/to/download]
```

To get full instruction of command usage we can type
```bash
python3 simulators.py install --help
```

## Shieldhit
todo

## Topas
todo

## Fluka
todo