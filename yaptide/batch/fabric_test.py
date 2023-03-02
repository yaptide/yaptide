from fabric import Connection, Result

login = "---------------"
host = "ares"
connection = Connection(host=f'{login}@{host}.cyfronet.pl', connect_kwargs={"password": "---------------"})
script = """#!/bin/bash
#SBATCH --ntasks 1
#SBATCH --time=00:00:19
#SBATCH -A plgccbmc11-cpu

echo Hello World!
"""
connection.run('rm new_script.sh')
connection.run(f'echo \'{script}\' >> new_script.sh')
connection.run('chmod 777 new_script.sh')
result: Result = connection.run('batch new_script.sh')
stdout = result.stdout.split()

job_id = int(stdout[3])
print(job_id)
