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
from botocore.exceptions import (ClientError, EndpointConnectionError, NoCredentialsError, ConnectTimeoutError)
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class SimulatorType(IntEnum):
    """Simulator types"""

    shieldhit = auto()
    fluka = auto()
    topas = auto()


def extract_shieldhit_from_tar_gz(archive_path: Path, unpacking_directory: Path, member_name: str,
                                  destination_dir: Path):
    """Extracts a single file from a tar.gz archive"""
    with tarfile.open(archive_path, "r:gz") as tar:
        # print all members
        for member in tar.getmembers():
            if Path(member.name).name == member_name and Path(member.name).parent.name == 'bin':
                click.echo(f"Extracting {member.name}")
                tar.extract(member, unpacking_directory)
                # move to installation path
                local_file_path = unpacking_directory / member.name
                click.echo(f"Moving {local_file_path} to {destination_dir}")
                shutil.move(local_file_path, destination_dir / member_name)


def extract_shieldhit_from_zip(archive_path: Path, unpacking_dir: Path, member_name: str, destination_dir: Path):
    """Extracts a single file from a zip archive"""
    with zipfile.ZipFile(archive_path) as zip_handle:
        # print all members
        for member in zip_handle.infolist():
            click.echo(f"Member: {member.filename}")
            if Path(member.filename).name == member_name:
                click.echo(f"Extracting {member.filename}")
                zip_handle.extract(member, unpacking_dir)
                # move to installation path
                local_file_path = Path(unpacking_dir) / member.filename
                destination_file_path = destination_dir / member_name
                click.echo(f"Moving {local_file_path} to {destination_file_path}")
                # move file from temporary directory to installation path using shutils
                if not destination_file_path.exists():
                    shutil.move(local_file_path, destination_file_path)


def download_shieldhit_demo_version(destination_dir: Path) -> bool:
    """Download shieldhit demo version from shieldhit.org"""
    demo_version_url = 'https://shieldhit.org/download/DEMO/shield_hit12a_x86_64_demo_gfortran_v1.1.0.tar.gz'
    # check if working on Windows
    if platform.system() == 'Windows':
        demo_version_url = 'https://shieldhit.org/download/DEMO/shield_hit12a_win64_demo_v1.1.0.zip'

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
        click.echo(f"Extracting {temp_file_archive} to {destination_dir}")
        destination_dir.mkdir(parents=True, exist_ok=True)
        if temp_file_archive.suffix == '.gz':
            extract_shieldhit_from_tar_gz(temp_file_archive,
                                          Path(tmpdir_name),
                                          'shieldhit',
                                          destination_dir=destination_dir)
        elif temp_file_archive.suffix == '.zip':
            extract_shieldhit_from_zip(temp_file_archive,
                                       Path(tmpdir_name),
                                       'shieldhit.exe',
                                       destination_dir=destination_dir)
    return True


def check_if_s3_connection_is_working(s3_client: boto3.client) -> bool:
    """Check if connection to S3 is possible"""
    try:
        s3_client.list_buckets()
    except NoCredentialsError as e:
        click.echo(f"No credentials found. Check your access key and secret key. {e}", err=True)
        return False
    except EndpointConnectionError as e:
        click.echo(f"Could not connect to the specified endpoint. {e}", err=True)
        return False
    except ConnectTimeoutError as e:
        click.echo(f"Connection timeout. {e}", err=True)
        return False
    except ClientError as e:
        click.echo(f"An error occurred while connecting to S3: {e.response['Error']['Message']}", err=True)
        return False
    return True


def download_shieldhit_from_s3(
    destination_dir: Path,
    endpoint: str,
    access_key: str,
    secret_key: str,
    password: str,
    salt: str,
    bucket: str,
    key: str,
    decrypt: bool = True,
) -> bool:
    """Download SHIELD-HIT12A from S3 bucket"""
    s3_client = boto3.client("s3",
                             aws_access_key_id=access_key,
                             aws_secret_access_key=secret_key,
                             endpoint_url=endpoint)

    if not validate_connection_data(bucket=bucket, key=key, s3_client=s3_client):
        return False

    destination_file_path = destination_dir / 'shieldhit'
    # append '.exe' to file name if working on Windows
    if platform.system() == 'Windows':
        destination_file_path = destination_dir / 'shieldhit.exe'

    download_and_decrypt_status = download_file(key=key,
                                                bucket=bucket,
                                                s3_client=s3_client,
                                                decrypt=decrypt,
                                                password=password,
                                                salt=salt,
                                                destination_file_path=destination_file_path)

    if not download_and_decrypt_status:
        return False

    return True


def download_shieldhit_from_s3_or_from_website(
    destination_dir: Path,
    endpoint: str,
    access_key: str,
    secret_key: str,
    password: str,
    salt: str,
    bucket: str,
    key: str,
    decrypt: bool = True,
):
    """Download SHIELD-HIT12A from S3 bucket, if not available download demo version from shieldhit.org website"""
    download_ok = download_shieldhit_from_s3(destination_dir=destination_dir,
                                             endpoint=endpoint,
                                             access_key=access_key,
                                             secret_key=secret_key,
                                             password=password,
                                             salt=salt,
                                             bucket=bucket,
                                             key=key,
                                             decrypt=decrypt)
    if download_ok:
        click.echo('SHIELD-HIT12A downloaded from S3')
    else:
        click.echo('SHIELD-HIT12A download failed, trying to download demo version from shieldhit.org website')
        demo_download_ok = download_shieldhit_demo_version(destination_dir=destination_dir)
        if demo_download_ok:
            click.echo('SHIELD-HIT12A demo version downloaded from shieldhit.org website')
        else:
            click.echo('SHIELD-HIT12A demo version download failed')


# skipcq: PY-R1000
def download_topas_from_s3(download_dir: Path, endpoint: str, access_key: str, secret_key: str, bucket: str, key: str,
                           version: str, geant4_bucket: str) -> bool:
    """Download TOPAS from S3 bucket"""
    s3_client = boto3.client("s3",
                             aws_access_key_id=access_key,
                             aws_secret_access_key=secret_key,
                             endpoint_url=endpoint)

    if not validate_connection_data(bucket, key, s3_client):
        return False

    # Download TOPAS tar
    topas_temp_file = tempfile.NamedTemporaryFile()
    try:
        response = s3_client.list_object_versions(
            Bucket=bucket,
            Prefix=key,
        )
        topas_file_downloaded = False
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
                    topas_file_downloaded = True
        if not topas_file_downloaded:
            click.echo(f"Could not find TOPAS version {version} in bucket {bucket}, file {key}", err=True)
            return False

    except ClientError as e:
        click.echo("Failed to download TOPAS from S3 with error: ", e.response["Error"]["Message"])
        return False

    # Download GEANT4 tar files
    geant4_temp_files = []

    objects = s3_client.list_objects_v2(Bucket=geant4_bucket)

    try:
        for obj in objects['Contents']:
            key = obj['Key']
            response = s3_client.list_object_versions(
                Bucket=geant4_bucket,
                Prefix=key,
            )
            for curr_version in response["Versions"]:
                version_id = curr_version["VersionId"]
                tags = s3_client.get_object_tagging(
                    Bucket=geant4_bucket,
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
                            s3_client.download_fileobj(Bucket=geant4_bucket,
                                                       Key=key,
                                                       Fileobj=temp_file,
                                                       ExtraArgs={"VersionId": version_id})
                            geant4_temp_files.append(temp_file)

    except ClientError as e:
        click.echo("Failed to download Geant4 data from S3 with error: ", e.response["Error"]["Message"])
        return False

    topas_temp_file.seek(0)
    topas_file_contents = tarfile.TarFile(fileobj=topas_temp_file)
    click.echo(f"Unpacking {topas_temp_file.name} to {download_dir}")
    topas_file_contents.extractall(path=download_dir)
    topas_extracted_path = download_dir / "topas" / "bin" / "topas"
    topas_extracted_path.chmod(0o700)
    click.echo(f"Installed TOPAS into {download_dir}")

    geant4_files_path = download_dir / "geant4_files_path"
    if not geant4_files_path.exists():
        try:
            geant4_files_path.mkdir()
        except OSError as e:
            click.echo(f"Could not create directory {geant4_files_path}: {e}", err=True)
            return False
    for file in geant4_temp_files:
        file.seek(0)
        file_contents = tarfile.TarFile(fileobj=file)
        click.echo(f"Unpacking {file.name} to {geant4_files_path}")
        file_contents.extractall(path=geant4_files_path)
    click.echo(f"Installed Geant4 files into {geant4_files_path}")
    return True


def extract_fluka_from_tar_gz(archive_path: Path, unpacking_directory: Path, destination_dir: Path) -> bool:
    """Extracts a single directory from a tar.gz archive"""
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(path=unpacking_directory)
        content = list(unpacking_directory.iterdir())
        if len(content) == 1:
            shutil.copytree(str(content[0]), str(destination_dir / 'fluka'), dirs_exist_ok=True)
            return True
        if len(content) > 1:
            shutil.copytree(str(unpacking_directory), str(destination_dir / 'fluka'), dirs_exist_ok=True)
            return True
    return False


def download_fluka_from_s3(download_dir: Path, endpoint: str, access_key: str, secret_key: str, bucket: str,
                           password: str, salt: str, key: str) -> bool:
    """Download (and decrypt) Fluka from S3 bucket"""
    s3_client = boto3.client("s3",
                             aws_access_key_id=access_key,
                             aws_secret_access_key=secret_key,
                             endpoint_url=endpoint)

    if not validate_connection_data(bucket, key, s3_client):
        return False

    with tempfile.TemporaryDirectory() as tmpdir_name:
        tmp_dir = Path(tmpdir_name).resolve()
        tmp_archive = tmp_dir / 'fluka.tgz'
        tmp_dir_path = tmp_dir / 'fluka'
        download_and_decrypt_status = download_file(key=key,
                                                    bucket=bucket,
                                                    s3_client=s3_client,
                                                    decrypt=True,
                                                    password=password,
                                                    salt=salt,
                                                    destination_file_path=tmp_archive)
        if not download_and_decrypt_status:
            return False
        download_and_decrypt_status = extract_fluka_from_tar_gz(archive_path=tmp_archive,
                                                                unpacking_directory=tmp_dir_path,
                                                                destination_dir=download_dir)

    return download_and_decrypt_status


def upload_file_to_s3(bucket: str,
                      file_path: Path,
                      endpoint: str,
                      access_key: str,
                      secret_key: str,
                      encrypt: bool = False,
                      encryption_password: str = '',
                      encryption_salt: str = '') -> bool:
    """Upload file to S3 bucket"""
    # Create S3 client
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        endpoint_url=endpoint,
    )
    if not check_if_s3_connection_is_working(s3_client):
        import socket
        hostname = s3_client._endpoint.host.strip("https://")
        click.echo(f"S3 connection to {hostname}, checking IP....", err=True)
        ip = socket.gethostbyname(hostname)
        click.echo(f"S3 connection to {hostname} / {ip} failed", err=True)
        return False

    # Check if bucket exists and create if not
    if bucket not in [bucket["Name"] for bucket in s3_client.list_buckets()["Buckets"]]:
        click.echo(f"Bucket {bucket} does not exist. Creating.")
        s3_client.create_bucket(Bucket=bucket)

    # Encrypt file
    file_contents = file_path.read_bytes()
    if encrypt:
        click.echo(f"Encrypting file {file_path}")
        file_contents = encrypt_file(file_path, encryption_password, encryption_salt)
    try:
        # Upload encrypted file to S3 bucket
        click.echo(f"Uploading file {file_path}")
        s3_client.put_object(Body=file_contents, Bucket=bucket, Key=file_path.name)
        return True
    except ClientError as e:
        click.echo("Upload failed with error: ", e.response["Error"]["Message"])
        return False


def encrypt_file(file_path: Path, password: str, salt: str) -> bytes:
    """Encrypts a file using Fernet"""
    encryption_key = derive_key(password, salt)
    # skipcq: PTC-W6004
    bytes_from_file = file_path.read_bytes()
    fernet = Fernet(encryption_key)
    encrypted = fernet.encrypt(bytes_from_file)
    return encrypted


def decrypt_file(file_path: Path, password: str, salt: str) -> bytes:
    """Decrypts a file using Fernet"""
    encryption_key = derive_key(password, salt)
    # skipcq: PTC-W6004
    bytes_from_file = file_path.read_bytes()
    fernet = Fernet(encryption_key)
    try:
        decrypted = fernet.decrypt(bytes_from_file)
    except cryptography.fernet.InvalidToken:
        click.echo("Decryption failed - invalid token (password+salt)", err=True)
        return b''
    return decrypted


def validate_connection_data(bucket: str, key: str, s3_client) -> bool:
    """Validate S3 connection"""
    if not check_if_s3_connection_is_working(s3_client):
        import socket
        hostname = s3_client._endpoint.host.strip("https://")
        click.echo(f"S3 connection to {hostname}, checking IP....", err=True)
        ip = socket.gethostbyname(hostname)
        click.echo(f"S3 connection to {hostname} / {ip} failed", err=True)
        return False

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

    return True


def download_file(key: str,
                  bucket: str,
                  s3_client,
                  destination_file_path: Path,
                  decrypt: bool = False,
                  password: str = '',
                  salt: str = ''):
    """Handle download with encryption"""
    try:
        with tempfile.NamedTemporaryFile() as temp_file:
            click.echo(f"Downloading {key} from {bucket} to {temp_file.name}")
            s3_client.download_fileobj(Bucket=bucket, Key=key, Fileobj=temp_file)

            if decrypt:
                click.echo("Decrypting downloaded file")
                if not password or not salt:
                    click.echo("Password or salt not set", err=True)
                    return False
                bytes_from_decrypted_file = decrypt_file(file_path=Path(temp_file.name), password=password, salt=salt)
                if not bytes_from_decrypted_file:
                    click.echo("Decryption failed", err=True)
                    return False

                Path(destination_file_path).parent.mkdir(parents=True, exist_ok=True)
                Path(destination_file_path).write_bytes(bytes_from_decrypted_file)
            else:
                click.echo(f"Copying {temp_file.name} to {destination_file_path}")
                shutil.copy2(temp_file.name, destination_file_path)
    except ClientError as e:
        click.echo(f"S3 download failed with client error: {e}", err=True)
        return False

    destination_file_path.chmod(0o700)
    return True


def derive_key(password: str, salt: str) -> bytes:
    """Derives a key from the password and salt"""
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt.encode(), iterations=480_000)
    key = urlsafe_b64encode(kdf.derive(password.encode()))
    return key
