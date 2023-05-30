import os
import shutil
import tarfile
import tempfile
from enum import IntEnum, auto
from pathlib import Path
import zipfile

import click
import requests
import boto3
from cryptography.fernet import Fernet


class SimulatorType(IntEnum):
    """Table types"""

    shieldhit = auto()
    fluka = auto()
    topas = auto()


@click.group()
def run():
    """Manage simulators"""


installation_path = Path(__file__).resolve().parent.parent.parent / 'bin'


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

        if "SHIELDHIT_S3_BUCKET" in os.environ:
            click.echo("Downloading shieldhit from S3 bucket")
            endpoint, access_key, secret_key, encryption_key = os.environ["SHIELDHIT_S3_BUCKET"].split()
            s3_client = boto3.client(
                "s3",
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                endpoint_url=endpoint
            )
            destination_file_path = installation_path / "shieldhit"
            # Download file from s3 bucket
            with open(destination_file_path, "wb") as f:
                s3_client.download_fileobj("shieldhit", "shieldhit", f)
            # Decrypt downloaded file
            click.echo("Decrypting downloaded file")
            fernet = Fernet(encryption_key)
            with open(destination_file_path, "rb") as f:
                encrypted_data = f.read()
            decrypted_data = fernet.decrypt(encrypted_data)
            with open(destination_file_path, "wb") as f:
                f.write(decrypted_data)
            # Permission to execute
            os.chmod(destination_file_path, 0o755)
        else:
            demo_version_url = 'https://shieldhit.org/download/DEMO/shield_hit12a_x86_64_demo_gfortran_v1.0.1.tar.gz'
            # check if working on Windows
            if os.name == 'nt':
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
    else:
        click.echo('Not implemented')
        return False
    return True


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


if __name__ == "__main__":
    run()
