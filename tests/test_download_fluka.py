import os
import sys
import pytest
import logging
from pathlib import Path
from yaptide.admin.simulator_storage import download_fluka_from_s3


def check_if_environment_variables_set() -> bool:
    """Check if environment variables are set"""
    result = True
    for var_name in ['S3_ENDPOINT', 'S3_ACCESS_KEY', 'S3_SECRET_KEY', 'S3_FLUKA_BUCKET', 'S3_FLUKA_KEY']:
        if var_name not in os.environ:
            logging.error('variable %s not set', var_name)
            result = False
    return result


@pytest.mark.skipif(sys.platform == "win32", reason="FLUKA does not work on Windows.")
def test_if_fluka_downloaded(tmpdir):
    """Check if FLUKA is downloaded and can be executed"""
    if check_if_environment_variables_set():
        assert download_fluka_from_s3(
            download_dir=tmpdir,
            endpoint=os.getenv("S3_ENDPOINT"),
            access_key=os.getenv("S3_ACCESS_KEY"),
            secret_key=os.getenv("S3_SECRET_KEY"),
            bucket=os.getenv("S3_FLUKA_BUCKET"),
            password=os.getenv("S3_ENCRYPTION_PASSWORD"),
            salt=os.getenv("S3_ENCRYPTION_SALT"),
            key=os.getenv("S3_FLUKA_KEY"),
        )

        expected_rfluka_path = Path(tmpdir / "fluka" / "bin" / "rfluka")
        expected_lib_path = Path(tmpdir / "fluka" / "lib")
        assert expected_rfluka_path.exists(), "Expected FLUKA path does not exist."
        assert expected_rfluka_path.stat().st_size > 0, "Expected FLUKA path is empty."
        assert expected_lib_path.exists(), "Expected FLUKA lib does not exist."
    else:
        logging.warning("S3 environment variables are not set, skipping test.")
        pytest.skip("S3 environment variables are not set.")
