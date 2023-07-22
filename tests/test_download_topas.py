import os
import sys
import pytest
from pathlib import Path
from yaptide.admin.simulators import download_topas_from_s3


def check_if_environment_variables_set() -> bool:
    """Check if environment variables are set"""
    result = True
    if not 'S3_ENDPOINT' in os.environ:
        result = False
    if not 'S3_ACCESS_KEY' in os.environ:
        result = False
    if not 'S3_SECRET_KEY' in os.environ:
        result = False
    if not 'S3_TOPAS_BUCKET' in os.environ:
        result = False
    if not 'S3_TOPAS_KEY' in os.environ:
        result = False
    if not 'S3_GEANT_BUCKET' in os.environ:
        result = False
    if not 'S3_TOPAS_VERSION' in os.environ:
        result = False
    return result

@pytest.mark.skipif(sys.platform == "win32", reason="TOPAS does not work on Windows.")
def test_if_topas_downloaded(tmpdir):
    """Check if TOPAS is downloaded and can be executed"""
    if check_if_environment_variables_set():
        bucket = os.getenv("S3_TOPAS_BUCKET")
        key = os.getenv("S3_TOPAS_KEY")
        version = os.getenv("S3_TOPAS_VERSION")
        geant_bucket = os.getenv("S3_GEANT_BUCKET")
        assert download_topas_from_s3(bucket=bucket, key=key, version=version, geant_bucket=geant_bucket, path=tmpdir) is True
        expected_path = Path(tmpdir / "topas" / key)
        assert expected_path.exists()
        command = f"{expected_path} --version"
        assert os.system(command) == 0