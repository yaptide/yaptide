#! /usr/bin/env python

# import logging
import os
from pathlib import Path
# import platform
# import shutil
# import tarfile
# import tempfile
# import zipfile
# from base64 import urlsafe_b64encode
# from enum import IntEnum, auto
# from pathlib import Path

# import boto3
import click
# import cryptography
# import requests
# from botocore.exceptions import (ClientError, EndpointConnectionError,
#                                  NoCredentialsError)
# from cryptography.fernet import Fernet
# from cryptography.hazmat.primitives import hashes
# from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from dotenv import load_dotenv

from yaptide.admin.simulator_storage import SimulatorType, decrypt_file, download_simulator, encrypt_file, upload_file_to_s3

load_dotenv()
endpoint = os.getenv('S3_ENDPOINT')
access_key = os.getenv('S3_ACCESS_KEY')
secret_key = os.getenv('S3_SECRET_KEY')
password = os.getenv('S3_ENCRYPTION_PASSWORD')
salt = os.getenv('S3_ENCRYPTION_SALT')
shieldhit_bucket = os.getenv('S3_SHIELDHIT_BUCKET')
shieldhit_key = os.getenv('S3_SHIELDHIT_KEY')
topas_bucket_name = os.getenv('S3_TOPAS_BUCKET')
topas_key = os.getenv('S3_TOPAS_KEY')
topas_version = os.getenv('S3_TOPAS_VERSION')
geant4_bucket_name = os.getenv('S3_GEANT4_BUCKET')
fluka_bucket = os.getenv('S3_FLUKA_BUCKET')
fluka_key = os.getenv('S3_FLUKA_KEY')


@click.group()
def run():
    """Manage simulators"""


@run.command
@click.option('--name', required=True, type=click.Choice([sim.name for sim in SimulatorType]))
@click.option('--path', required=True, type=click.Path(writable=True, file_okay=True, dir_okay=False, path_type=Path))
@click.option('-v', '--verbose', count=True)
def download(**kwargs):
    """download simulator"""
    click.echo(f'Downloading simulator: {kwargs["name"]} to path {kwargs["path"]}')
    sim_type = SimulatorType[kwargs['name']]
    installation_status = download_simulator(sim_type, kwargs['path'])
    if installation_status:
        click.echo(f'Simulator {sim_type.name} installed')
    else:
        click.echo(f'Simulator {sim_type.name} installation failed')


@run.command
@click.option('--bucket', type=click.STRING, required=True, help='S3 bucket name')
@click.option('--file',
              type=click.Path(exists=True, readable=True, file_okay=True, dir_okay=False, path_type=Path),
              required=True,
              help='Path to file to upload')
@click.option('--endpoint',
              type=click.STRING,
              required=True,
              envvar='S3_ENDPOINT',
              default=endpoint,
              help='S3 endpoint')
@click.option('--access_key',
              type=click.STRING,
              required=True,
              envvar='S3_ACCESS_KEY',
              default=access_key,
              help='S3 access key')
@click.option('--secret_key',
              type=click.STRING,
              required=True,
              envvar='S3_SECRET_KEY',
              default=secret_key,
              help='S3 secret key')
@click.option('--password',
              type=click.STRING,
              envvar='S3_ENCRYPTION_PASSWORD',
              default=password,
              help='encryption password')
@click.option('--salt', type=click.STRING, envvar='S3_ENCRYPTION_SALT', default=salt, help='encryption salt')
def upload(**kwargs):
    """Upload simulator file to S3 bucket"""
    click.echo(f'Uploading file {kwargs["file"]} to bucket {kwargs["bucket"]}')
    upload_status = upload_file_to_s3(bucket=kwargs['bucket'],
                                      file_path=kwargs['file'],
                                      endpoint_url=kwargs['endpoint'],
                                      aws_access_key_id=kwargs['access_key'],
                                      aws_secret_access_key=kwargs['secret_key'],
                                      encryption_password=kwargs['password'],
                                      encryption_salt=kwargs['salt'])
    if upload_status:
        click.echo('File uploaded successfully')


@run.command
@click.option('--infile',
              type=click.Path(exists=True, readable=True, file_okay=True, dir_okay=False, path_type=Path),
              required=True,
              help='Path to file to encrypt')
@click.option('--outfile',
              type=click.Path(writable=True, file_okay=True, dir_okay=False, path_type=Path),
              required=True,
              help='Path where encrypted file is saved')
@click.option('--password',
              type=click.STRING,
              required=True,
              envvar='S3_ENCRYPTION_PASSWORD',
              default=password,
              help='encryption password')
@click.option('--salt',
              type=click.STRING,
              required=True,
              envvar='S3_ENCRYPTION_SALT',
              default=salt,
              help='encryption salt')
def encrypt(**kwargs):
    """Encrypt a file"""
    encrypted_bytes = encrypt_file(file_path=kwargs['infile'],
                                   encryption_password=kwargs['password'],
                                   encryption_salt=kwargs['salt'])
    outfile_path = Path(kwargs['outfile'])
    outfile_path.write_bytes(encrypted_bytes)


@run.command
@click.option('--infile',
              type=click.Path(exists=True, readable=True, file_okay=True, dir_okay=False, path_type=Path),
              required=True,
              help='Path to file to decrypt')
@click.option('--outfile',
              type=click.Path(writable=True, file_okay=True, dir_okay=False, path_type=Path),
              required=True,
              help='Path where decrypted file is saved')
@click.option('--password',
              type=click.STRING,
              required=True,
              envvar='S3_ENCRYPTION_PASSWORD',
              default=password,
              help='encryption password')
@click.option('--salt',
              type=click.STRING,
              required=True,
              envvar='S3_ENCRYPTION_SALT',
              default=salt,
              help='encryption salt')
def decrypt(**kwargs):
    """Decrypt a file"""
    decrypted_bytes = decrypt_file(file_path=kwargs['infile'],
                                   encryption_password=kwargs['password'],
                                   encryption_salt=kwargs['salt'])
    outfile_path = Path(kwargs['outfile'])
    outfile_path.write_bytes(decrypted_bytes)


if __name__ == "__main__":
    run()
