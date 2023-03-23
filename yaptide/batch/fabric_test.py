import argparse
import io

from fabric import Connection, Result
from paramiko import Ed25519Key

from datetime import datetime
import time

from string_templates import SUBMIT_SHIELDHIT, ARRAY_SHIELDHIT_BASH, COLLECT_BASH

from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument('--login', help='plgrid login', type=str)
args = parser.parse_args()

login = args.login
host = "ares.cyfronet.pl"

ROOT_DIR = Path(__file__).parent.resolve()
ssh_key_path = Path(ROOT_DIR, "id_ed25519")

# below code is for testing io
with open(ssh_key_path, "r") as reader:
    ssh_key_content = reader.read()
pkey = Ed25519Key(file_obj=io.StringIO(ssh_key_content))

utc_time = int(datetime.utcnow().timestamp()*1e6)
con = Connection(host=f'{login}@{host}', connect_kwargs={"pkey": pkey})

result: Result = con.run("echo $SCRATCH", hide=True)
scratch = result.stdout.split()[0]

job_dir = f"{scratch}/yaptide_runs/{utc_time}"

con.run(f"mkdir -p {job_dir}")

submit_file = f'{job_dir}/yaptide_submitter.sh'
array_file = f'{job_dir}/array_script.sh'
collect_file = f'{job_dir}/collect_script.sh'

input_files_dir = Path(ROOT_DIR, "input_files")  # not in repo (wastes)
input_files = {}
for filename in input_files_dir.iterdir():
    with open(filename, "r") as reader:
        input_files[filename.name] = reader.read()

submit_script = SUBMIT_SHIELDHIT.format(
    root_dir=job_dir,
    beam=input_files["beam.dat"],
    detect=input_files["detect.dat"],
    geo=input_files["geo.dat"],
    mat=input_files["mat.dat"],
    n_tasks=str(1)
)
array_script = ARRAY_SHIELDHIT_BASH.format(
    root_dir=job_dir,
    particle_no=str(1000)
)
collect_script = COLLECT_BASH.format(
    root_dir=job_dir
)

con.run(f'echo \'{array_script}\' >> {array_file}')
con.run(f'chmod 777 {array_file}')
con.run(f'echo \'{submit_script}\' >> {submit_file}')
con.run(f'chmod 777 {submit_file}')
con.run(f'echo \'{collect_script}\' >> {collect_file}')
con.run(f'chmod 777 {collect_file}')

result: Result = con.run(f'sh {submit_file}', hide=True)
lines = result.stdout.split("\n")
job_id = lines[0].split()[-1]
collect_id = lines[1].split()[-1]
print(job_id, collect_id)

print(f'ls {job_dir}/output')

while True:
    time.sleep(10)
    result: Result = con.run(f'sacct -j {collect_id} --format State', hide=True)
    collect_state = result.stdout.split()[-1].split()[0]
    if collect_state == "FAILED":
        print('Job state: FAILED')
        break
    if collect_state == "RUNNING":
        print('Job state: RUNNING')
        continue
    if collect_state == "COMPLETED":
        print('Job state: COMPLETED')
        result: Result = con.run(f'ls -f {job_dir}/output | grep .bdo', hide=True)
        for filename in result.stdout.split():
            file_path = Path(ROOT_DIR, "output", filename)
            with open(file_path, "wb") as writer:
                try:
                    con.get(f'{job_dir}/output/{filename}', writer)
                except FileNotFoundError:
                    print(filename)
        break
    result: Result = con.run(f'sacct -j {job_id} --format State', hide=True)
    job_state = result.stdout.split()[-1].split()[0]
    if job_state == "PENDING":
        print('Job state: PENDING')
        continue
    if job_state == "RUNNING":
        print('Job state: RUNNING')
        continue
    if collect_state == "PENDING":
        print('Job state: RUNNING')
        continue
