import os
from pathlib import Path
from yaptide.admin.simulators import download_shieldhit_from_s3


def test_if_environment_variables_set():
    """Check if environment variables are set"""
    assert 'S3_ENDPOINT' in os.environ
    assert 'S3_ACCESS_KEY' in os.environ
    assert 'S3_SECRET_KEY' in os.environ
    assert 'S3_ENCRYPTION_KEY' in os.environ


def test_if_shieldhit_downloaded(tmpdir):
    """Check if shieldhit is downloaded and can be executed"""
    installation_path = tmpdir
    assert download_shieldhit_from_s3(bucket="shieldhit", key="shieldhit", installation_path=installation_path) is True
    expected_path = Path(installation_path / "shieldhit")
    assert expected_path.exists()
    command = f"{expected_path} --version"
    assert os.system(command) == 0
