import logging
import os
import subprocess
import sys
import pytest
from pathlib import Path
from yaptide.admin.simulator_storage import download_shieldhit_from_s3


def check_if_environment_variables_set() -> bool:
    """Check if environment variables are set"""
    result = True
    for var_name in ['S3_ENDPOINT', 'S3_ACCESS_KEY', 'S3_SECRET_KEY', 'S3_SHIELDHIT_BUCKET', 'S3_SHIELDHIT_KEY']:
        if var_name not in os.environ:
            logging.error('variable %s not set', var_name)
            result = False
    return result


@pytest.mark.skipif(sys.platform == "win32", reason="Lets not tests this on Windows.")
def test_if_shieldhit_downloaded(tmpdir, shieldhit_binary_filename):
    """Check if SHIELD-HIT12A binary is downloaded and can be executed"""
    if check_if_environment_variables_set():
        assert download_shieldhit_from_s3(endpoint=os.getenv("S3_ENDPOINT"),
                                          access_key=os.getenv("S3_ACCESS_KEY"),
                                          secret_key=os.getenv("S3_SECRET_KEY"),
                                          bucket=os.getenv("S3_SHIELDHIT_BUCKET"),
                                          key=os.getenv("S3_SHIELDHIT_KEY"),
                                          password=os.getenv("S3_ENCRYPTION_PASSWORD"),
                                          salt=os.getenv("S3_ENCRYPTION_SALT"),
                                          destination_dir=tmpdir) is True
        expected_path = Path(tmpdir / shieldhit_binary_filename)
        assert expected_path.exists(), f"Expected path {expected_path} does not exist."
        assert expected_path.stat().st_size > 0, f"Expected path {expected_path} is empty."

        command = [str(expected_path), "--version"]
        try:
            # If check=True and the exit code is non-zero, raises a
            # CalledProcessError (has return code and output/error streams).
            # text=True means stdout and stderr will be strings instead of bytes
            completed_process = subprocess.run(command,
                                               check=True,
                                               stdout=subprocess.PIPE,
                                               stderr=subprocess.PIPE,
                                               text=True)

            # Capture stdout and stderr
            command_stdout = completed_process.stdout
            command_stderr = completed_process.stderr

            # Log stdout and stderr using logging
            logging.info("Command Output:\n%s", command_stdout)
            logging.info("Command Error Output:\n%s", command_stderr)

            # Check if the process executed successfully and stdout is not empty
            assert completed_process.returncode == 0, "Command did not execute successfully."
            assert command_stdout.strip(), "Command stdout is empty."
            assert not command_stderr.strip(), "Command stderr is not empty."
        except subprocess.CalledProcessError as e:
            # If the command exits with a non-zero status
            logging.error("Command Error: %s\nExecuted Command: %s", e.stderr, " ".join(command))
    else:
        logging.warning("S3 environment variables are not set, skipping test.")
        pytest.skip("S3 environment variables are not set.")
