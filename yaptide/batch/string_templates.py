SUBMIT_SHIELDHIT: str = """#!/bin/bash
OUT=`mktemp`
export PATH="$PATH:$PLG_GROUPS_STORAGE/plggccbmc"
module load gcc/11.3.0

ROOT_DIR={root_dir}
cd $ROOT_DIR
mkdir -p $ROOT_DIR/workspaces/task_{{0001..{n_tasks}}}
mkdir -p $ROOT_DIR/input

BEAM_FILE=$ROOT_DIR/input/beam.dat
GEO_FILE=$ROOT_DIR/input/geo.dat
MAT_FILE=$ROOT_DIR/input/mat.dat
DETECT_FILE=$ROOT_DIR/input/detect.dat
WATCHER_FILE=$ROOT_DIR/watcher.py
ARRAY_SCRIPT=$ROOT_DIR/array_script.sh
COLLECT_SCRIPT=$ROOT_DIR/collect_script.sh

cat << EOF > $BEAM_FILE
{beam}
EOF
cat << EOF > $GEO_FILE
{geo}
EOF
cat << EOF > $MAT_FILE
{mat}
EOF
cat << EOF > $DETECT_FILE
{detect}
EOF
cat << EOF > $WATCHER_FILE
{watcher}
EOF

SHIELDHIT_CMD="sbatch --array=1-{n_tasks} --time=00:04:59\\
    -A plgccbmc11-cpu --partition=plgrid-testing --parsable $ARRAY_SCRIPT > $OUT"
eval $SHIELDHIT_CMD
JOB_ID=`cat $OUT | cut -d ";" -f 1`
echo "Job id: $JOB_ID"

if [ -n "$JOB_ID" ] ; then
    COLLECT_CMD="sbatch --dependency=afterany:$JOB_ID\\
        --time=00:00:59 -A plgccbmc11-cpu --partition=plgrid-testing --parsable $COLLECT_SCRIPT > $OUT"
    eval $COLLECT_CMD
    COLLECT_ID=`cat $OUT | cut -d ";" -f 1`
    echo "Collect id: $COLLECT_ID"
fi
"""  # skipcq: FLK-E501

COLLECT_BASH: str = """#!/bin/bash
ROOT_DIR={root_dir}
INPUT_WILDCARD=$ROOT_DIR/workspaces/task_*/*.bdo
OUTPUT_DIRECTORY=$ROOT_DIR/output

cd $ROOT

mkdir -p $OUTPUT_DIRECTORY

for INPUT_FILE in $INPUT_WILDCARD; do
  cp $INPUT_FILE $OUTPUT_DIRECTORY
done
"""  # skipcq: FLK-E501

ARRAY_SHIELDHIT_BASH: str = """#!/bin/bash

ROOT_DIR={root_dir}
WORK_DIR=$ROOT_DIR/workspaces/task_`printf %04d $SLURM_ARRAY_TASK_ID`
echo $WORK_DIR

# seed of RNG
RNG_SEED=$SLURM_ARRAY_TASK_ID

# main SHIELD-HIT12A input files
BEAM_FILE=$ROOT_DIR/input/beam.dat
GEO_FILE=$ROOT_DIR/input/geo.dat
MAT_FILE=$ROOT_DIR/input/mat.dat
DETECT_FILE=$ROOT_DIR/input/detect.dat
WATCHER_FILE=$ROOT_DIR/watcher.py

# go to working directory
cd $WORK_DIR
pwd

sig_handler()
{{
    echo "BATCH interrupted"
    wait # wait for all children, this is important!
}}

FILE_TO_WATCH=$WORK_DIR/shieldhit_`printf %04d $SLURM_ARRAY_TASK_ID`.log
srun python3 $WATCHER_FILE --filepath=$FILE_TO_WATCH\\
    --job_id=$SLURM_JOB_ID --task_id=$SLURM_ARRAY_TASK_ID &

trap 'sig_handler' SIGUSR1

# execute simulation
srun shieldhit --beamfile=$BEAM_FILE --geofile=$GEO_FILE --matfile=$MAT_FILE --detectfile=$DETECT_FILE\\
    -n {particle_no} -N $RNG_SEED  $WORK_DIR &

wait
"""  # skipcq: FLK-E501

PYTHON_WATCHER_SCRIPT: str = """from pathlib import Path
import re
import time
import argparse
import signal

def log_generator(thefile):
    while True:
        line = thefile.readline()
        if not line:
            time.sleep(1)
            continue
        yield line


def read_file(filepath: Path, job_id: str, task_id: int):
    run_match = r"\\bPrimary particle no.\\s*\\d*\\s*ETR:\\s*\\d*\\s*hour.*\\d*\\s*minute.*\\d*\\s*second.*\\b"
    complete_match = r"\\bRun time:\\s*\\d*\\s*hour.*\\d*\\s*minute.*\\d*\\s*second.*\\b"
    requested_match = r"\\bRequested number of primaries NSTAT"

    logfile = None
    for _ in range(30):  # 30 stands for maximum attempts
        try:
            logfile = open(filepath)  # skipcq: PTC-W6004
            break
        except FileNotFoundError:
            time.sleep(3)

    if logfile is None:
        up_dict = {
            "task_state": "FAILED"
        }
        print(f"Update for task: {{task_id}} - FAILED")
        return

    loglines = log_generator(logfile)
    for line in loglines:
        if re.search(run_match, line):
            splitted = line.split()
            up_dict = {
                "simulated_primaries": int(splitted[3]),
                "estimated_time": {
                    "hours": int(splitted[5]),
                    "minutes": int(splitted[7]),
                    "seconds": int(splitted[9]),
                }
            }
            print(f"Update for task: {{task_id}} - simulated primaries: {{splitted[3]}}")

        elif re.search(requested_match, line):
            splitted = line.split(": ")
            up_dict = {
                "simulated_primaries": 0,
                "requested_primaries": int(splitted[1]),
                "task_state": "RUNNING"
            }
            print(f"Update for task: {{task_id}} - RUNNING")

        elif re.search(complete_match, line):
            splitted = line.split()
            up_dict = {
                "run_time": {
                    "hours": int(splitted[2]),
                    "minutes": int(splitted[4]),
                    "seconds": int(splitted[6]),
                },
                "task_state": "COMPLETED"
            }
            print(f"Update for task: {{task_id}} - COMPLETED")
            return


if __name__ == '__main__':
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)

    parser = argparse.ArgumentParser()
    parser.add_argument('--filepath', type=str)
    parser.add_argument('--job_id', type=str)
    parser.add_argument('--task_id', type=int)
    args = parser.parse_args()
    filepath = Path(args.filepath)
    job_id = args.job_id
    task_id = args.task_id

    print(filepath, job_id, task_id)

    read_file(filepath, job_id, task_id)
"""  # skipcq: FLK-E501
