#! /usr/bin/env python

import logging
import os
import platform
import shutil
import tarfile
import tempfile
import zipfile
from base64 import urlsafe_b64encode
from enum import IntEnum, auto
from pathlib import Path

import boto3
import click
import cryptography
import requests
from botocore.exceptions import (ClientError, EndpointConnectionError,
                                 NoCredentialsError)
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from dotenv import load_dotenv


class SimulatorType(IntEnum):
    """Table types"""

    shieldhit = auto()
    fluka = auto()
    topas = auto()


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
geant_bucket_name = os.getenv('S3_GEANT_BUCKET')


@click.group()
def run():
    """Manage simulators"""


@run.command
def installed(**kwargs):
    """List installed simulators"""
    click.echo('to be implemented')


def extract_shieldhit_from_tar_gz(archive_path: Path, destination_dir: Path, member_name: str, shieldhit_path: Path):
    """Extracts a single file from a tar.gz archive"""
    with tarfile.open(archive_path, "r:gz") as tar:
        # print all members
        for member in tar.getmembers():
            if Path(member.name).name == member_name and Path(member.name).parent.name == 'bin':
                click.echo(f"Extracting {member.name}")
                tar.extract(member, destination_dir)
                # move to installation path
                local_file_path = Path(destination_dir) / member.name
                click.echo(f"Moving {local_file_path} to {shieldhit_path}")
                shutil.move(local_file_path, shieldhit_path / member_name)


def extract_shieldhit_from_zip(archive_path: Path, destination_dir: Path, member_name: str, shieldhit_path: Path):
    """Extracts a single file from a zip archive"""
    with zipfile.ZipFile(archive_path) as zip_handle:
        # print all members
        for member in zip_handle.infolist():
            click.echo(f"Member: {member.filename}")
            if Path(member.filename).name == member_name:
                click.echo(f"Extracting {member.filename}")
                zip_handle.extract(member, destination_dir)
                # move to installation path
                local_file_path = Path(destination_dir) / member.filename
                destination_file_path = shieldhit_path / member_name
                click.echo(f"Moving {local_file_path} to {destination_file_path}")
                # move file from temporary directory to installation path using shutils
                if not destination_file_path.exists():
                    shutil.move(local_file_path, destination_file_path)


def install_simulator(sim_name: SimulatorType, installation_path: Path) -> bool:
    """Add simulator to database"""
    click.echo(f'Installation for simulator: {sim_name.name} started')
    logging.info("Installation for simulator: %s started", sim_name.name)
    if sim_name == SimulatorType.shieldhit:
        click.echo(f'Installing shieldhit into {installation_path}')
        logging.info("Installing shieldhit into %s", installation_path)
        installation_path.mkdir(exist_ok=True, parents=True)
        download_status = False
        if all([endpoint, access_key, secret_key]):
            click.echo('Downloading from S3 bucket')
            logging.info("Downloading from S3 bucket")
            download_status = download_shieldhit_from_s3(shieldhit_path=installation_path)
        if not download_status:
            click.echo('Downloading demo version from shieldhit.org')
            logging.info("Downloading demo version from shieldhit.org")
            download_status = download_shieldhit_demo_version(shieldhit_path=installation_path)
    elif sim_name == SimulatorType.topas:
        click.echo(f'Installing TOPAS into {installation_path}')
        logging.info("Installing TOPAS into %s", installation_path)
        installation_path.mkdir(exist_ok=True, parents=True)
        if all([endpoint, access_key, secret_key]):
            click.echo('Downloading from S3 bucket')
            logging.info("Downloading from S3 bucket")
            download_status = download_topas_from_s3(path=installation_path)
        else:
            click.echo('Cannot download from S3 bucket, missing environment variables')
            logging.info("Cannot download from S3 bucket, missing environment variables")
            return False
    else:
        click.echo('Not implemented')
        return False
    return download_status


def download_shieldhit_demo_version(shieldhit_path: Path) -> bool:
    """Download shieldhit demo version from shieldhit.org"""
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

    # Download TOPAS tar
    topas_temp_file = tempfile.NamedTemporaryFile()
    try:
        response = s3_client.list_object_versions(
            Bucket=bucket,
            Prefix=key,
        )
        for curr_version in response["Versions"]:
            version_id = curr_version["VersionId"]
            tags = s3_client.get_object_tagging(
                Bucket=bucket,
                Key=key,
                VersionId=version_id,
            )
            for tag in tags["TagSet"]:
                if tag["Key"] == "version" and tag["Value"] == version:
                    click.echo(f"Downloading {key}, version {version} from {bucket} to {topas_temp_file.name}")
                    s3_client.download_fileobj(Bucket=bucket,
                                               Key=key,
                                               Fileobj=topas_temp_file,
                                               ExtraArgs={"VersionId": version_id})
    except ClientError as e:
        click.echo("Failed to download TOPAS from S3 with error: ", e.response["Error"]["Message"])
        return False

    # Download GEANT tar files
    geant_temp_files = []

    objects = s3_client.list_objects_v2(Bucket=geant_bucket)

    try:
        for obj in objects['Contents']:
            key = obj['Key']
            response = s3_client.list_object_versions(
                Bucket=geant_bucket,
                Prefix=key,
            )
            for curr_version in response["Versions"]:
                version_id = curr_version["VersionId"]
                tags = s3_client.get_object_tagging(
                    Bucket=geant_bucket,
                    Key=key,
                    VersionId=version_id,
                )
                for tag in tags["TagSet"]:
                    if tag["Key"] == "topas_versions":
                        topas_versions = tag["Value"].split(",")
                        topas_versions = [version.strip() for version in topas_versions]
                        if version in topas_versions:
                            temp_file = tempfile.NamedTemporaryFile()
                            click.echo(f"""Downloading {key} for TOPAS version {version}
                                           from {bucket} to {temp_file.name}""")
                            s3_client.download_fileobj(Bucket=geant_bucket,
                                                       Key=key,
                                                       Fileobj=temp_file,
                                                       ExtraArgs={"VersionId": version_id})
                            geant_temp_files.append(temp_file)

    except ClientError as e:
        click.echo("Failed to download Geant4 from S3 with error: ", e.response["Error"]["Message"])
        return False

    topas_temp_file.seek(0)
    topas_file_contents = tarfile.TarFile(fileobj=topas_temp_file)
    click.echo(f"Unpacking {topas_temp_file.name} to {path}")
    topas_file_contents.extractall(path=path)
    topas_extracted_path = path / "topas" / "bin" / "topas"
    topas_extracted_path.chmod(0o700)
    logging.info("Installed TOPAS into %s", path)
    click.echo(f"Installed TOPAS into {path}")

    geant_files_path = path / "geant4_files_path"
    if not geant_files_path.exists():
        try:
            geant_files_path.mkdir()
        except OSError as e:
            click.echo("Could not create installation directory")
            return False
    for file in geant_temp_files:
        file.seek(0)
        file_contents = tarfile.TarFile(fileobj=file)
        click.echo(f"Unpacking {file.name} to {geant_files_path}")
        file_contents.extractall(path=geant_files_path)
    logging.info("Installed Geant4 files into %s", geant_files_path)
    click.echo(f"Installed Geant4 files into {geant_files_path}")
    return True


def upload_file_to_s3(
        bucket: str,
        file_path: Path,
        endpoint_url: str = endpoint,
        aws_access_key_id: str = access_key,
        aws_secret_access_key: str = secret_key,
        encryption_password: str = password,
        encryption_salt: str = salt
        ) -> bool:
    """Upload file to S3 bucket"""
    # Create S3 client
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        endpoint_url=endpoint_url,
    )
    if not check_if_s3_connection_is_working(s3_client):
        click.echo("S3 connection failed", err=True)
        return False

    # Check if bucket exists and create if not
    if bucket not in [bucket["Name"] for bucket in s3_client.list_buckets()["Buckets"]]:
        click.echo("Bucket does not exist. Creating bucket.")
        s3_client.create_bucket(Bucket=bucket)

    # Encrypt file
    encrypted_file_contents = encrypt_file(file_path, encryption_password, encryption_salt)
    try:
        # Upload encrypted file to S3 bucket
        click.echo(f"Uploading file {file_path}")
        s3_client.put_object(Body=encrypted_file_contents, Bucket=bucket, Key=file_path.name)
        return True
    except ClientError as e:
        click.echo("Upload failed with error: ", e.response["Error"]["Message"])
        return False


def encrypt_file(file_path: Path, encryption_password: str = password, encryption_salt: str = salt) -> bytes:
    """Encrypts a file using Fernet"""
    encryption_key = derive_key(encryption_password, encryption_salt)
    # skipcq: PTC-W6004
    with open(file_path, "rb") as file:
        original = file.read()
    fernet = Fernet(encryption_key)
    encrypted = fernet.encrypt(original)
    return encrypted


def decrypt_file(file_path: Path, encryption_password: str = password, encryption_salt: str = salt) -> bytes:
    """Decrypts a file using Fernet"""
    encryption_key = derive_key(encryption_password, encryption_salt)
    # skipcq: PTC-W6004
    with open(file_path, "rb") as file:
        encrypted = file.read()
    fernet = Fernet(encryption_key)
    try:
        decrypted = fernet.decrypt(encrypted)
    except cryptography.fernet.InvalidToken:
        click.echo("Decryption failed - invalid token (password+salt)", err=True)
        return b''
    return decrypted


def derive_key(encryption_password: str = password, encryption_salt: str = salt) -> bytes:
    """Derives a key from the password and salt"""
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=encryption_salt.encode(), iterations=480_000)
    key = urlsafe_b64encode(kdf.derive(encryption_password.encode()))
    return key


@run.command
@click.option('--name', type=click.Choice([sim.name for sim in SimulatorType]))
@click.option('--path', type=click.Path(file_okay=False, path_type=Path))
@click.option('-v', '--verbose', count=True)
def install(**kwargs):
    """List installed simulators"""
    if 'name' not in kwargs or kwargs['name'] is None:
        click.echo('Please specify a simulator name using --name option, possible values are: ', nl=False)
        for sim in SimulatorType:
            click.echo(f'{sim.name} ', nl=False)
        return
    if 'path' not in kwargs or kwargs['path'] is None:
        click.echo('Please specify installation path')
        return
    click.echo(f'Installing simulator: {kwargs["name"]} to path {kwargs["path"]}')
    sim_type = SimulatorType[kwargs['name']]
    if install_simulator(sim_type, kwargs['path']):
        click.echo(f'Simulator {sim_type.name} installed')
    else:
        click.echo(f'Simulator {sim_type.name} installation failed')


@run.command
@click.option('--bucket', help='S3 bucket name')
@click.option('--file', help='Path to file to upload')
@click.option('--endpoint', envvar='S3_ENDPOINT', default=endpoint, help='S3 endpoint')
@click.option('--access_key', envvar='S3_ACCESS_KEY', default=access_key, help='S3 access key')
@click.option('--secret_key', envvar='S3_SECRET_KEY', default=secret_key, help='S3 secret key')
@click.option('--password', envvar='S3_ENCRYPTION_PASSWORD', default=password, help='S3 encryption password')
@click.option('--salt', envvar='S3_ENCRYPTION_SALT', default=salt, help='S3 encryption salt')
def upload(**kwargs):
    """Manage arguments and upload file to S3 bucket"""
    args = ['bucket', 'file', 'endpoint', 'access_key', 'secret_key', 'password', 'salt']
    messages = [
        'Bucket name is required specify with --bucket',
        'Path to file is required specify with --file',
        'S3 endpoint not found in environment variables specify with --endpoint',
        'S3 access key not found in environment variables specify with --access_key',
        'S3 secret key not found in environment variables specify with --secret_key',
        'S3 encryption password not found in environment variables specify with --password',
        'S3 encryption salt not found in environment variables specify with --salt'
    ]
    for arg, message in zip(args, messages):
        if not kwargs[arg] or kwargs[arg] is None:
            click.echo(message)
            return
    if not Path(kwargs['file']).exists():
        click.echo('File does not exist')
        return
    if upload_file_to_s3(
        bucket=kwargs['bucket'],
        file_path=Path(kwargs['file']),
        endpoint_url=kwargs['endpoint'],
        aws_access_key_id=kwargs['access_key'],
        aws_secret_access_key=kwargs['secret_key'],
        encryption_password=kwargs['password'],
        encryption_salt=kwargs['salt']
            ):
        click.echo('File uploaded successfully')


if __name__ == "__main__":
    run()
