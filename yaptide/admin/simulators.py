import os
import shutil
import tarfile
import tempfile
import zipfile
import click
import requests
import boto3
import platform
from enum import IntEnum, auto
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from botocore.exceptions import NoCredentialsError, EndpointConnectionError, ClientError
from dotenv import load_dotenv
from base64 import urlsafe_b64encode


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
installation_path = Path(__file__).resolve().parent.parent.parent / 'bin'


@click.group()
def run():
    """Manage simulators"""


@run.command
def installed(**kwargs):
    """List installed simulators"""
    click.echo('to be implemented')


def extract_shieldhit_from_tar_gz(archive_path: Path, destination_dir: Path, member_name: str):
    """Extracts a single file from a tar.gz archive"""
    with tarfile.open(archive_path, "r:gz") as tar:
        # print all members
        for member in tar.getmembers():
            if Path(member.name).name == member_name and Path(member.name).parent.name == 'bin':
                click.echo(f"Extracting {member.name}")
                tar.extract(member, destination_dir)
                # move to installation path
                local_file = Path(destination_dir) / member.name
                click.echo(f"Moving {local_file} to {installation_path}")
                local_file.rename(installation_path / member_name)


def extract_shieldhit_from_zip(archive_path: Path, destination_dir: Path, member_name: str):
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
                destination_file_path = installation_path / member_name
                click.echo(f"Moving {local_file_path} to {installation_path}")
                # move file from temporary directory to installation path using shutils
                if not destination_file_path.exists():
                    shutil.move(local_file_path, destination_file_path)


def install_simulator(name: SimulatorType) -> bool:
    """Add simulator to database"""
    click.echo(f'Installation for simulator: {name} started')
    if name == SimulatorType.shieldhit:
        click.echo(f'Installing shieldhit into {installation_path}')
        installation_path.mkdir(exist_ok=True, parents=True)
        shieldhit_downloaded_from_s3 = False
        if all([endpoint, access_key, secret_key, password, salt]):
            click.echo('Downloading from S3 bucket')
            shieldhit_downloaded_from_s3 = download_shieldhit_from_s3()
        if not shieldhit_downloaded_from_s3:
            click.echo('Downloading demo version from shieldhit.org')
            download_shieldhit_demo_version()
    else:
        click.echo('Not implemented')
        return False
    return True


def download_shieldhit_demo_version() -> bool:
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
        click.echo(f"Extracting {temp_file_archive} to {installation_path}")
        if temp_file_archive.suffix == '.gz':
            extract_shieldhit_from_tar_gz(temp_file_archive, Path(tmpdir_name), 'shieldhit')
        elif temp_file_archive.suffix == '.zip':
            extract_shieldhit_from_zip(temp_file_archive, Path(tmpdir_name), 'shieldhit.exe')
    return True


def download_shieldhit_from_s3(
        bucket: str = shieldhit_bucket,
        key: str = shieldhit_key,
        installation_path: Path = installation_path   # skipcq: PYL-W0621
        ) -> bool:
    """Download shieldhit from S3 bucket"""
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        endpoint_url=endpoint
    )
    destination_file_path = installation_path / key
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    # Download file from s3 bucket
    try:
        s3_client.download_fileobj(Bucket=bucket, Key=key, Fileobj=temp_file)
    except ClientError as e:
        click.echo("S3 download failed with error: ", e.response["Error"]["Message"])
        return False
    # Decrypt downloaded file
    click.echo("Decrypting downloaded file")
    decrypted_file_contents = decrypt_file(temp_file.name, password, salt)
    with open(destination_file_path, "wb") as f:
        f.write(decrypted_file_contents)
    # Permission to execute
    os.chmod(destination_file_path, 0o700)
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
    # Check if connection to S3 is possible
    try:
        s3_client.list_buckets()
    except NoCredentialsError as e:
        click.echo(f"No credentials found. Check your access key and secret key. {e}")
        return False
    except EndpointConnectionError as e:
        click.echo(f"Could not connect to the specified endpoint. {e}")
        return False
    except ClientError as e:
        click.echo(f"An error occurred while connecting to S3: {e.response['Error']['Message']}")
        return False

    # Check if bucket exists and create if not
    if bucket not in [bucket["Name"] for bucket in s3_client.list_buckets()["Buckets"]]:
        click.echo("Bucket does not exist. Creating bucket.")
        s3_client.create_bucket(Bucket=bucket)

    # Encrypt file
    encrypted_file_contents = encrypt_file(file_path, encryption_password, encryption_salt)
    try:
        # Upload encrypted file to S3 bucket
        click.echo("Uploading file.")
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
    decrypted = fernet.decrypt(encrypted)
    return decrypted


def derive_key(encryption_password: str = password, encryption_salt: str = salt) -> bytes:
    """Derives a key from the password and salt"""
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=encryption_salt.encode(), iterations=480_000)
    key = urlsafe_b64encode(kdf.derive(encryption_password.encode()))
    return key


@run.command
@click.option('--name', type=click.Choice([sim.name for sim in SimulatorType]))
@click.option('-v', '--verbose', count=True)
def install(**kwargs):
    """List installed simulators"""
    if 'name' not in kwargs or kwargs['name'] is None:
        click.echo('Please specify a simulator name using --name option, possible values are: ', nl=False)
        for sim in SimulatorType:
            click.echo(f'{sim.name} ', nl=False)
        return
    click.echo(f'Installing simulator: {kwargs["name"]}')
    sim_type = SimulatorType[kwargs['name']]
    if install_simulator(sim_type):
        click.echo(f'Simulator {sim_type.name} installed')


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
