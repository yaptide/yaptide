#! /usr/bin/env python

import os
from pathlib import Path
import click

from dotenv import load_dotenv

if __name__ == "__main__":
    # we need to add the main directory to the path so that we can import the yaptide package
    import sys
    this_file_path = Path(__file__).resolve()
    sys.path.insert(0, str(this_file_path.parent.parent.parent))
from yaptide.admin.simulator_storage import decrypt_file, download_fluka_from_s3, download_shieldhit_demo_version, download_shieldhit_from_s3, download_simulator, download_topas_from_s3, encrypt_file, upload_file_to_s3

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


def s3credentials(required: bool = False):
    """
    Collection of options for S3 credentials
    """

    def decorator(func):
        func = click.option('--endpoint',
                            type=click.STRING,
                            required=required,
                            envvar='S3_ENDPOINT',
                            default=endpoint,
                            help='S3 endpoint')(func)
        func = click.option('--access_key',
                            type=click.STRING,
                            required=required,
                            envvar='S3_ACCESS_KEY',
                            default=access_key,
                            help='S3 access key')(func)
        func = click.option('--secret_key',
                            type=click.STRING,
                            required=required,
                            envvar='S3_SECRET_KEY',
                            default=secret_key,
                            help='S3 secret key')(func)
        return func

    return decorator


def encryption_options(required: bool = False):
    """
    Collection of options for S3 credentials
    """

    def decorator(func):
        func = click.option('--password',
                            type=click.STRING,
                            envvar='S3_ENCRYPTION_PASSWORD',
                            default=password,
                            required=required,
                            help='encryption password')(func)
        func = click.option('--salt',
                            type=click.STRING,
                            envvar='S3_ENCRYPTION_SALT',
                            default=password,
                            required=required,
                            help='encryption salt')(func)
        return func

    return decorator


@run.command
@click.option('--infile',
              type=click.Path(exists=True, readable=True, file_okay=True, dir_okay=False, path_type=Path),
              required=True,
              help='file to encrypt')
@click.option('--outfile',
              type=click.Path(writable=True, file_okay=True, dir_okay=False, path_type=Path),
              required=True,
              help='Path where encrypted file is saved')
@encryption_options(required=True)
def encrypt(**kwargs):
    """Encrypt a file"""
    encrypted_bytes = encrypt_file(file_path=kwargs['infile'], password=kwargs['password'], salt=kwargs['salt'])
    outfile_path = Path(kwargs['outfile'])
    outfile_path.parent.mkdir(parents=True, exist_ok=True)
    outfile_path.write_bytes(encrypted_bytes)


@run.command
@click.option('--infile',
              type=click.Path(exists=True, readable=True, file_okay=True, dir_okay=False, path_type=Path),
              required=True,
              help='file to decrypt')
@click.option('--outfile',
              type=click.Path(writable=True, file_okay=True, dir_okay=False, path_type=Path),
              required=True,
              help='Path where decrypted file is saved')
@encryption_options(required=True)
def decrypt(**kwargs):
    """Decrypt a file"""
    decrypted_bytes = decrypt_file(file_path=kwargs['infile'], password=kwargs['password'], salt=kwargs['salt'])
    outfile_path = Path(kwargs['outfile'])
    outfile_path.parent.mkdir(parents=True, exist_ok=True)
    outfile_path.write_bytes(decrypted_bytes)


@run.command
@click.option('--dir',
              required=True,
              type=click.Path(writable=True, file_okay=False, dir_okay=True, path_type=Path),
              help='download directory')
@click.option('--bucket', type=click.STRING, envvar='S3_FLUKA_BUCKET', required=True, help='S3 bucket name')
@click.option('--key', type=click.STRING, envvar='S3_FLUKA_KEY', required=True, help='S3 key (filename)')
@s3credentials()
@encryption_options(required=True)
def download_fluka(**kwargs):
    """Download Fluka simulator"""
    click.echo(f'Downloading Fluka into directory {kwargs["dir"]}')
    installation_status = download_fluka_from_s3(download_dir=kwargs['dir'],
                                                 endpoint=kwargs['endpoint'],
                                                 access_key=kwargs['access_key'],
                                                 secret_key=kwargs['secret_key'],
                                                 bucket=kwargs['bucket'],
                                                 key=kwargs['key'],
                                                 password=kwargs['password'],
                                                 salt=kwargs['salt'])
    if installation_status:
        click.echo(f'Fluka installed')
    else:
        click.echo(f'Fluka installation failed')


@run.command
@click.option('--dir',
              required=True,
              type=click.Path(writable=True, file_okay=False, dir_okay=True, path_type=Path),
              help='download directory')
@click.option('--topas_bucket',
              type=click.STRING,
              envvar='S3_TOPAS_BUCKET',
              required=True,
              help='S3 bucket name with TOPAS binary')
@click.option('--geant4_bucket',
              type=click.STRING,
              envvar='S3_GEANT4_BUCKET',
              required=True,
              help='S3 bucket name with Geant4 data')
@click.option('--topas_key', type=click.STRING, envvar='S3_TOPAS_KEY', required=True, help='S3 key (filename)')
@click.option('--topas_version', type=click.STRING, envvar='S3_TOPAS_VERSION', required=True, help='TOPAS version')
@s3credentials()
def download_topas(**kwargs):
    """Download TOPAS simulator and Geant4 data"""
    click.echo(f'Downloading TOPAS into directory {kwargs["dir"]}')
    installation_status = download_topas_from_s3(
        download_dir=kwargs['dir'],
        endpoint=kwargs['endpoint'],
        access_key=kwargs['access_key'],
        secret_key=kwargs['secret_key'],
        bucket=kwargs['topas_bucket'],
        key=kwargs['topas_key'],
        version=kwargs['topas_version'],
        geant4_bucket=kwargs['geant4_bucket'],
    )
    if installation_status:
        click.echo(f'TOPAS installed')
    else:
        click.echo(f'TOPAS installation failed')


@run.command
@click.option('--dir',
              required=True,
              type=click.Path(writable=True, file_okay=False, dir_okay=True, path_type=Path),
              help='download directory')
@click.option('--bucket', type=click.STRING, envvar='S3_SHIELDHIT_BUCKET', help='S3 bucket name')
@click.option('--key', type=click.STRING, envvar='S3_SHIELDHIT_KEY', help='S3 key (filename)')
@click.option('--decrypt', is_flag=True, default=False, help='decrypt file downloaded from S3')
@s3credentials()
@encryption_options()
def download_shieldhit(**kwargs):
    """Download SHIELD-HIT12A"""
    click.echo(f'Downloading SHIELD-HIT12A into directory {kwargs["dir"]}')
    click.echo(f'Decrypting SHIELD-HIT12A: {kwargs["decrypt"]}')
    download_ok = download_shieldhit_from_s3(destination_dir=kwargs['dir'],
                                             endpoint=kwargs['endpoint'],
                                             access_key=kwargs['access_key'],
                                             secret_key=kwargs['secret_key'],
                                             password=kwargs['password'],
                                             salt=kwargs['salt'],
                                             bucket=kwargs['bucket'],
                                             key=kwargs['key'],
                                             decrypt=kwargs['decrypt'])
    if download_ok:
        click.echo(f'SHIELD-HIT12A downloaded from S3')
    else:
        click.echo(f'SHIELD-HIT12A download failed, trying to download demo version from shieldhit.org website')
        demo_download_ok = download_shieldhit_demo_version(destination_dir=kwargs['dir'])
        if demo_download_ok:
            click.echo(f'SHIELD-HIT12A demo version downloaded from shieldhit.org website')
        else:
            click.echo(f'SHIELD-HIT12A demo version download failed')


@run.command
@click.option('--bucket', type=click.STRING, required=True, help='S3 bucket name')
@click.option('--file',
              type=click.Path(exists=True, readable=True, file_okay=True, dir_okay=False, path_type=Path),
              required=True,
              help='file to upload')
@s3credentials()
@encryption_options()
def upload(**kwargs):
    """Upload simulator file to S3 bucket"""
    click.echo(f'Uploading file {kwargs["file"]} to bucket {kwargs["bucket"]}')
    upload_status = upload_file_to_s3(bucket=kwargs['bucket'],
                                      file_path=kwargs['file'],
                                      endpoint=kwargs['endpoint'],
                                      access_key=kwargs['access_key'],
                                      secret_key=kwargs['secret_key'],
                                      encryption_password=kwargs['password'],
                                      encryption_salt=kwargs['salt'])
    if upload_status:
        click.echo('File uploaded successfully')


if __name__ == "__main__":
    run()
