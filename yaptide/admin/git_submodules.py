import subprocess
import shutil
import logging
import os


def find_git_executable():
    """Function returns git executable path or None"""
    git_path = shutil.which('git')
    return git_path


def check_submodules_folders_exist():
    """Function checking if submodules folders exists on system"""
    with open('.gitmodules') as f:
        logging.info("Found .gitmodules file")
        for line in f:
            if 'path' in line:
                logging.info("Found submodule line in .gitmodules: %s", line)
                submodule_path = line.split('=')[-1].strip()

                # Check if folder exists and is not empty
                if not os.path.exists(submodule_path) or not os.listdir(submodule_path):
                    raise RuntimeError("Submodules are missing! Please use: git submodule update --init --recursive")


def check_submodules():
    """Function checking the status of Git submodules"""
    try:
        git_path = find_git_executable()

        if git_path is None:
            logging.info("Git executable not found")
            check_submodules_folders_exist()
            return

        logging.info("Found git executable path: %s", git_path)
        result = subprocess.run([git_path, "submodule", "status"], capture_output=True, text=True, check=True)
        for line in result.stdout.splitlines():
            if line.startswith('-') or line.startswith('+'):
                raise RuntimeError("Submodules are missing! Please use: git submodule update --init --recursive")

    except subprocess.CalledProcessError as e:
        logging.error("Error running 'git submodule status': %s", e)
