import os
from pathlib import Path
from yaptide.admin.simulators import download_shieldhit_from_s3


def check_if_environment_variables_set() -> bool:
    """Check if environment variables are set"""
    result = True
    if not 'S3_ENDPOINT' in os.environ:
        result = False
    if not 'S3_ACCESS_KEY' in os.environ:
        result = False
    if not 'S3_SECRET_KEY' in os.environ:
        result = False
    if not 'S3_ENCRYPTION_PASSWORD' in os.environ:
        result = False
    if not 'S3_ENCRYPTION_SALT' in os.environ:
        result = False
    if not 'S3_SHIELDHIT_BUCKET' in os.environ:
        result = False
    if not 'S3_SHIELDHIT_KEY' in os.environ:
        result = False
    return result


def test_if_shieldhit_downloaded(tmpdir):
    """Check if shieldhit is downloaded and can be executed"""
    if check_if_environment_variables_set():
        bucket = os.getenv("S3_SHIELDHIT_BUCKET")
        key = os.getenv("S3_SHIELDHIT_KEY")
        assert download_shieldhit_from_s3(bucket=bucket, key=key, installation_path=tmpdir) is True
        expected_path = Path(tmpdir / key)
        assert expected_path.exists()
        command = f"{expected_path} --version"
        assert os.system(command) == 0