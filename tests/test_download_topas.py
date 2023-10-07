import os
import sys
import pytest
import logging
import subprocess
from pathlib import Path
from yaptide.admin.simulators import download_topas_from_s3


def check_if_environment_variables_set() -> bool:
    """Check if environment variables are set"""
    result = True
    for var_name in ['S3_ENDPOINT', 'S3_ACCESS_KEY', 'S3_SECRET_KEY', 'S3_TOPAS_BUCKET', 'S3_TOPAS_KEY', 'S3_GEANT_BUCKET','S3_TOPAS_VERSION']:
        if var_name not in os.environ:
            logging.error(' variable %s not set', var_name)
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
        expected_path = Path(tmpdir / "topas" / "topas" / "bin" / "topas")
        expected_geant_path = Path(tmpdir / "geant")
        assert expected_path.exists(), "Expected TOPAS path does not exist."
        assert expected_path.stat().st_size > 0, "Expected TOPAS path is empty."
        assert expected_geant_path.exists(), "Expected Geant path does not exist."

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
            assert command_stdout.strip()==os.environ['S3_TOPAS_VERSION'], "Command stdout does not return the correct TOPAS version."
            assert not command_stderr.strip(), "Command stderr is not empty."
        except subprocess.CalledProcessError as e:
            # If the command exits with a non-zero status
            pytest.fail("Command Error: %s\nExecuted Command: %s", e.stderr, " ".join(command))
    else:
        logging.warning("S3 environment variables are not set, skipping test.")
        pytest.skip("S3 environment variables are not set.")