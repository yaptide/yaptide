from fabric import Connection, Result
from paramiko import Ed25519Key

import os

from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.realpath(__file__))
ssh_key_path = Path(ROOT_DIR, "id_ed25519")

pkey = Ed25519Key(filename=ssh_key_path)

login = "--------------"
host = "ares.cyfronet.pl"
connection = Connection(host=f'{login}@{host}', connect_kwargs={"pkey": pkey})
script = """#!/bin/bash
#SBATCH --ntasks 1
#SBATCH --time=00:00:19
#SBATCH -A plgccbmc11-cpu

echo Hello World!
"""
connection.run('rm new_script.sh')
connection.run(f'echo \'{script}\' >> new_script.sh')
connection.run('chmod 777 new_script.sh')
result: Result = connection.run('sbatch new_script.sh')
stdout = result.stdout.split()

job_id = int(stdout[3])
print(job_id)

connection.run(f'scancel {job_id}')
