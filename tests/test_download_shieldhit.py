import os
from pathlib import Path
from yaptide.admin.simulators import download_shieldhit_from_s3


def test_if_environment_variables_set():
    """Check if environment variables are set"""
    assert os.getenv('S3_ENDPOINT') is not None
    assert os.getenv('S3_ACCESS_KEY') is not None
    assert os.getenv('S3_SECRET_KEY') is not None
    assert os.getenv('S3_ENCRYPTION_PASSWORD') is not None
    assert os.getenv('S3_ENCRYPTION_SALT') is not None
    assert os.getenv('S3_SHIELDHIT_BUCKET') is not None
    assert os.getenv('S3_SHIELDHIT_KEY') is not None


def test_if_shieldhit_downloaded(tmpdir):
    """Check if shieldhit is downloaded and can be executed"""
    installation_path = tmpdir
    bucket = os.getenv("S3_SHIELDHIT_BUCKET")
    key = os.getenv("S3_SHIELDHIT_KEY")
    assert download_shieldhit_from_s3(bucket=bucket, key=key, installation_path=installation_path) is True
    expected_path = Path(installation_path / "shieldhit")
    assert expected_path.exists()
    command = f"{expected_path} --version"
    assert os.system(command) == 0
