from enum import IntEnum, auto
from pathlib import Path
import tempfile
import click
import requests


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
    return None


def install_simulator(name: SimulatorType) -> bool:
    """Add simulator to database"""
    click.echo(f'Installation for simulator: {name} started')
    if name == SimulatorType.shieldhit:
        click.echo(f'Installing shieldhit into {installation_path}')
        installation_path.mkdir(exist_ok=True, parents=True)

        demo_version_url = 'https://shieldhit.org/download/DEMO/shield_hit12a_x86_64_demo_gfortran_v1.0.0.tar.gz'
        # create temporary directory and download
        # Create a temporary file to store the downloaded binary data
        with tempfile.TemporaryDirectory() as tmpdir_name:
            click.echo(f"Downloading from {demo_version_url} to {tmpdir_name}")
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT x.y; rv:10.0) Gecko/20100101 Firefox/10.0'}
            response = requests.get(demo_version_url, headers=headers)
            temp_file_tar_gz = Path(tmpdir_name) / 'shieldhit.tar.gz'
            with open(temp_file_tar_gz, 'wb') as file_handle:
                file_handle.write(response.content)
            click.echo(f"Saved to {temp_file_tar_gz} with size {temp_file_tar_gz.stat().st_size} bytes")

            # extract
            click.echo(f"Extracting {temp_file_tar_gz} to {installation_path}")
            import tarfile
            with tarfile.open(temp_file_tar_gz, "r:gz") as tar:
                # print all members
                for member in tar.getmembers():
                    if Path(member.name).name == 'shieldhit' and Path(member.name).parent.name == 'bin':
                        click.echo(f"Extracting {member.name}")
                        tar.extract(member, tmpdir_name)
                        # move to installation path
                        local_file = Path(tmpdir_name) / member.name
                        click.echo(f"Moving {local_file} to {installation_path}")
                        local_file.rename(installation_path / 'shieldhit')
    else:
        click.echo('Not implemented')
        return False
    return True


@run.command
@click.option('--name', type=click.Choice([sim.name for sim in SimulatorType]))
@click.option('-v', '--verbose', count=True)
def install(**kwargs):
    """List installed simulators"""
    click.echo(f'Installing simulator: {kwargs["name"]}')
    sim_type = SimulatorType[kwargs['name']]
    if install_simulator(sim_type):
        click.echo(f'Simulator {sim_type.name} installed')
    return None


if __name__ == "__main__":
    run()
