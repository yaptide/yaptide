import os
import sys
import pytest
import logging
import subprocess
from pathlib import Path
from tests.conftest import check_if_environment_variables_set
from yaptide.admin.simulator_storage import download_topas_from_s3


@pytest.mark.skipif(sys.platform == "win32", reason="TOPAS does not work on Windows.")
def test_if_topas_downloaded(tmpdir):
    """Check if TOPAS is downloaded and can be executed"""
    variables = [
        'S3_ENDPOINT', 'S3_ACCESS_KEY', 'S3_SECRET_KEY', 'S3_TOPAS_BUCKET', 'S3_TOPAS_KEY', 'S3_GEANT4_BUCKET',
        'S3_TOPAS_VERSION'
    ]
    if check_if_environment_variables_set(variables):
        assert download_topas_from_s3(endpoint=os.getenv("S3_ENDPOINT"),
                                      access_key=os.getenv("S3_ACCESS_KEY"),
                                      secret_key=os.getenv("S3_SECRET_KEY"),
                                      bucket=os.getenv("S3_TOPAS_BUCKET"),
                                      key=os.getenv("S3_TOPAS_KEY"),
                                      version=os.getenv("S3_TOPAS_VERSION"),
                                      geant4_bucket=os.getenv("S3_GEANT4_BUCKET"),
                                      download_dir=tmpdir) is True
        expected_path = Path(tmpdir / "topas" / "bin" / "topas")
        assert expected_path.exists(), "Expected TOPAS path does not exist."
        assert expected_path.stat().st_size > 0, "Expected TOPAS path is empty."
        expected_geant4_path = Path(tmpdir / "geant4_files_path")
        assert expected_geant4_path.exists(), "Expected Geant4 path does not exist."

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
            assert command_stdout.strip(
            ) == os.environ['S3_TOPAS_VERSION'], "Command stdout does not return the correct TOPAS version."
            assert not command_stderr.strip(), "Command stderr is not empty."
        except subprocess.CalledProcessError as e:
            # If the command exits with a non-zero status
            pytest.fail("Command Error: %s\nExecuted Command: %s", e.stderr, " ".join(command))
    else:
        logging.warning("S3 environment variables are not set, skipping test.")
        pytest.skip("S3 environment variables are not set.")
