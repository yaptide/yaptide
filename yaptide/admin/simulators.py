#! /usr/bin/env python

from functools import wraps
import os
from pathlib import Path
import click

from dotenv import load_dotenv

if __name__ == "__main__":
    # we need to add the main directory to the path so that we can import the yaptide package
    import sys
    this_file_path = Path(__file__).resolve()
    sys.path.insert(0, str(this_file_path.parent.parent.parent))
from yaptide.admin.simulator_storage import (decrypt_file, download_fluka_from_s3,
                                             download_shieldhit_from_s3_or_from_website, download_topas_from_s3,
                                             encrypt_file, upload_file_to_s3)

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
    """Collection of options for S3 credentials"""

    def decorator(func):
        """Decorator for S3 credentials options"""

        @click.option('--endpoint',
                      type=click.STRING,
                      required=required,
                      envvar='S3_ENDPOINT',
                      default=endpoint,
                      help='S3 endpoint')
        @click.option('--access_key',
                      type=click.STRING,
                      required=required,
                      envvar='S3_ACCESS_KEY',
                      default=access_key,
                      help='S3 access key')
        @click.option('--secret_key',
                      type=click.STRING,
                      required=required,
                      envvar='S3_SECRET_KEY',
                      default=secret_key,
                      help='S3 secret key')
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


def encryption_options(required: bool = False):
    """Collection of options for encryption"""

    def decorator(func):
        """Decorator for encryption options"""

        @click.option('--password',
                      type=click.STRING,
                      envvar='S3_ENCRYPTION_PASSWORD',
                      default=password,
                      required=required,
                      help='encryption password')
        @click.option('--salt',
                      type=click.STRING,
                      envvar='S3_ENCRYPTION_SALT',
                      default=password,
                      required=required,
                      help='encryption salt')
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

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
@s3credentials(required=True)
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
        click.echo('Fluka installed')
    else:
        click.echo('Not implemented')
        return False
    return download_status


def download_shieldhit_demo_version(shieldhit_path: Path) -> bool:
    """Download SHIELD-HIT12A demo version from shieldhit.org"""
    logging.debug("Downloading SHIELD-HIT12A demo version")
    demo_version_url = 'https://shieldhit.org/download/DEMO/shield_hit12a_x86_64_demo_gfortran_v1.0.1.tar.gz'
    # check if working on Windows
    if platform.system() == 'Windows':
        demo_version_url = 'https://shieldhit.org/download/DEMO/shield_hit12a_win64_demo_v1.0.1.zip'

    # create temporary directory and download
    # Create a temporary file to store the downloaded binary data
    with tempfile.TemporaryDirectory() as tmpdir_name:
        click.echo(f"Downloading from {demo_version_url} to {tmpdir_name}")
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT x.y; rv:10.0) Gecko/20100101 Firefox/10.0'}
        response = requests.get(demo_version_url, headers=headers)
        temp_file_archive = Path(tmpdir_name) / Path(demo_version_url).name
        with open(temp_file_archive, 'wb') as file_handle:
            file_handle.write(response.content)
        click.echo(f"Saved to {temp_file_archive} with size {temp_file_archive.stat().st_size} bytes")

        # extract
        click.echo(f"Extracting {temp_file_archive} to {shieldhit_path}")
        if temp_file_archive.suffix == '.gz':
            extract_shieldhit_from_tar_gz(temp_file_archive, Path(tmpdir_name),
                                          'shieldhit', shieldhit_path=shieldhit_path)
        elif temp_file_archive.suffix == '.zip':
            extract_shieldhit_from_zip(temp_file_archive, Path(tmpdir_name),
                                       'shieldhit.exe', shieldhit_path=shieldhit_path)
    return True


def check_if_s3_connection_is_working(
        s3_client: boto3.client) -> bool:
    """Check if connection to S3 is possible"""
    try:
        s3_client.list_buckets()
    except NoCredentialsError as e:
        click.echo(f"No credentials found. Check your access key and secret key. {e}", err=True)
        return False
    except EndpointConnectionError as e:
        click.echo(f"Could not connect to the specified endpoint. {e}", err=True)
        return False
    except ClientError as e:
        click.echo(f"An error occurred while connecting to S3: {e.response['Error']['Message']}", err=True)
        return False
    return True


def download_shieldhit_from_s3(
        shieldhit_path: Path,
        bucket: str = shieldhit_bucket,
        key: str = shieldhit_key,
        ) -> bool:
    """Download shieldhit from S3 bucket"""
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        endpoint_url=endpoint
    )
    if not check_if_s3_connection_is_working(s3_client):
        click.echo("S3 connection failed", err=True)
        return False

    destination_file_path = shieldhit_path / 'shieldhit'
    # append '.exe' to file name if working on Windows
    if platform.system() == 'Windows':
        destination_file_path = shieldhit_path / 'shieldhit.exe'

    # Check if bucket name is valid
    if not bucket:
        click.echo("Bucket name is empty", err=True)
        return False

    # Check if key is valid
    if not key:
        click.echo("Key is empty", err=True)
        return False

    # Check if bucket exists
    try:
        s3_client.head_bucket(Bucket=bucket)
    except ClientError as e:
        click.echo(f"Problem accessing bucket named {bucket}: {e}", err=True)
        return False

    # Check if key exists
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
    except ClientError as e:
        click.echo(f"Problem accessing key named {key} in bucket {bucket}: {e}", err=True)
        return False

    # Download file from S3 bucket
    try:
        with tempfile.NamedTemporaryFile() as temp_file:
            click.echo(f"Downloading {key} from {bucket} to {temp_file.name}")
            s3_client.download_fileobj(Bucket=bucket, Key=key, Fileobj=temp_file)

            # if no password and salt is provided, skip decryption
            if password is None and salt is None:
                click.echo("No password and salt provided, skipping decryption")
                click.echo(f"Copying {temp_file.name} to {destination_file_path}")
                shutil.copy2(temp_file.name, destination_file_path)
            else:     # Decrypt downloaded file
                click.echo("Decrypting downloaded file")
                shieldhit_binary_bytes = decrypt_file(temp_file.name, password, salt)
                if not shieldhit_binary_bytes:
                    click.echo("Decryption failed", err=True)
                    return False
                with open(destination_file_path, "wb") as dest_file:
                    dest_file.write(shieldhit_binary_bytes)
    except ClientError as e:
        click.echo(f"S3 download failed with client error: {e}", err=True)
        return False
    # Permission to execute
    destination_file_path.chmod(0o700)
    return True


# skipcq: PY-R1000
def download_topas_from_s3(path: Path,
                           bucket: str = topas_bucket_name,
                           key: str = topas_key,
                           version: str = topas_version,
                           geant_bucket: str = geant_bucket_name
                           ) -> bool:
    """Download TOPAS from S3 bucket"""
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        endpoint_url=endpoint
    )

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
@s3credentials(required=True)
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
        click.echo('TOPAS installed')
    else:
        click.echo('TOPAS installation failed')


@run.command
@click.option('--dir',
              required=True,
              type=click.Path(writable=True, file_okay=False, dir_okay=True, path_type=Path),
              help='download directory')
@click.option('--bucket', type=click.STRING, envvar='S3_SHIELDHIT_BUCKET', help='S3 bucket name')
@click.option('--key', type=click.STRING, envvar='S3_SHIELDHIT_KEY', help='S3 key (filename)')
@click.option('--decrypt', is_flag=True, default=False, help='decrypt file downloaded from S3')
@s3credentials(required=False)
@encryption_options(required=False)
def download_shieldhit(**kwargs):
    """Download SHIELD-HIT12A"""
    click.echo(f'Downloading SHIELD-HIT12A into directory {kwargs["dir"]}')
    download_shieldhit_from_s3_or_from_website(destination_dir=kwargs['dir'],
                                               endpoint=kwargs['endpoint'],
                                               access_key=kwargs['access_key'],
                                               secret_key=kwargs['secret_key'],
                                               password=kwargs['password'],
                                               salt=kwargs['salt'],
                                               bucket=kwargs['bucket'],
                                               key=kwargs['key'],
                                               decrypt=kwargs['decrypt'])


@run.command
@click.option('--bucket', type=click.STRING, required=True, help='S3 bucket name')
@click.option('--file',
              type=click.Path(exists=True, readable=True, file_okay=True, dir_okay=False, path_type=Path),
              required=True,
              help='file to upload')
@click.option('--encrypt', is_flag=True, default=False, help='encrypt file uploaded to S3')
@s3credentials(required=True)
@encryption_options(required=False)
def upload(**kwargs):
    """Upload simulator file to S3 bucket"""
    click.echo(f'Uploading file {kwargs["file"]} to bucket {kwargs["bucket"]}')
    upload_status = upload_file_to_s3(bucket=kwargs['bucket'],
                                      file_path=kwargs['file'],
                                      endpoint=kwargs['endpoint'],
                                      access_key=kwargs['access_key'],
                                      secret_key=kwargs['secret_key'],
                                      encrypt=kwargs['encrypt'],
                                      encryption_password=kwargs['password'],
                                      encryption_salt=kwargs['salt'])
    if upload_status:
        click.echo('File uploaded successfully')


if __name__ == "__main__":
    run()
