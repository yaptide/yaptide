SUBMIT_SHIELDHIT: str = """#!/bin/bash
OUT=`mktemp`
module load shieldhit

ROOT_DIR={root_dir}
cd $ROOT_DIR
mkdir -p $ROOT_DIR/workspaces/task_{{0001..{n_tasks}}}
mkdir -p $ROOT_DIR/input


INPUT_DIR=$ROOT_DIR/input
ARRAY_SCRIPT=$ROOT_DIR/array_script.sh
COLLECT_SCRIPT=$ROOT_DIR/collect_script.sh

unzip -d $INPUT_DIR $ROOT_DIR/input.zip
rm $ROOT_DIR/input.zip

# the aggregator batches the progress updates of all tasks into single requests to the backend
AUTH_FILE=$ROOT_DIR/.zmq_auth
nohup python3 $ROOT_DIR/aggregator.py --sim_id={sim_id} --update_key={update_key} \
    --backend_url={backend_url} --root_dir=$ROOT_DIR --ntasks={n_tasks} \
    > $ROOT_DIR/aggregator.log 2>&1 &
AGGREGATOR_PID=$!

# tasks need the address the aggregator bound to, it writes it once the socket is up
for _ in $(seq 1 30); do
    [ -f $AUTH_FILE ] && break
    sleep 1
done
if [ ! -f $AUTH_FILE ] ; then
    echo "Aggregator failed to start, tasks will report directly to the backend"
    kill $AGGREGATOR_PID 2>/dev/null
fi

SHIELDHIT_CMD="sbatch --array=1-{n_tasks} {array_options} --parsable $ARRAY_SCRIPT > $OUT"
eval $SHIELDHIT_CMD
JOB_ID=`cat $OUT | cut -d ";" -f 1`
echo "Job id: $JOB_ID"

if [ -n "$JOB_ID" ] ; then
    COLLECT_CMD="sbatch --dependency=afterany:$JOB_ID {collect_options} --parsable $COLLECT_SCRIPT > $OUT"
    eval $COLLECT_CMD
    COLLECT_ID=`cat $OUT | cut -d ";" -f 1`
    echo "Collect id: $COLLECT_ID"
else
    # nothing will ever report to the aggregator, do not leave it running on the login node
    kill $AGGREGATOR_PID 2>/dev/null
    rm -f $AUTH_FILE
fi
"""  # skipcq: FLK-E501

COLLECT_SHIELDHIT_BASH: str = """#!/bin/bash
{collect_header}
ROOT_DIR={root_dir}
python3 $ROOT_DIR/simulation_data_sender.py --sim_id={sim_id} --update_key={update_key} \\
      --backend_url={backend_url} --simulation_state=MERGING_RUNNING

INPUT_WILDCARD=$ROOT_DIR/workspaces/task_*/*.bdo
OUTPUT_DIRECTORY=$ROOT_DIR/output

mkdir -p $OUTPUT_DIRECTORY

cd $OUTPUT_DIRECTORY

convertmc json --many "$INPUT_WILDCARD"

CLEAR_BDOS={remove_output_from_workspace}

if $CLEAR_BDOS; then
    rm $INPUT_WILDCARD
fi

python3 $ROOT_DIR/simulation_data_sender.py --output_dir=$OUTPUT_DIRECTORY \\
    --sim_id={sim_id} --update_key={update_key} --backend_url={backend_url}
"""  # skipcq: FLK-E501

ARRAY_SHIELDHIT_BASH: str = """#!/bin/bash
{array_header}
ROOT_DIR={root_dir}
WORK_DIR=$ROOT_DIR/workspaces/task_`printf %04d $SLURM_ARRAY_TASK_ID`

# seed of RNG
RNG_SEED=$SLURM_ARRAY_TASK_ID

# main SHIELD-HIT12A input files
INPUT_DIR=$ROOT_DIR/input

# go to working directory
cd $WORK_DIR

# make symbolic links to all files from input folder
ln -s $INPUT_DIR/* .

sig_handler()
{{
    echo "BATCH interrupted"
    wait # wait for all children, this is important!
}}

FILE_TO_WATCH=$WORK_DIR/shieldhit_`printf %04d $SLURM_ARRAY_TASK_ID`.log
python3 $ROOT_DIR/watcher.py \\
    --filepath=$FILE_TO_WATCH\\
    --sim_id={sim_id}\\
    --task_id=$SLURM_ARRAY_TASK_ID\\
    --update_key={update_key}\\
    --backend_url={backend_url}\\
    --zmq_auth=$ROOT_DIR/.zmq_auth\\
    --verbose 1>watcher_$SLURM_ARRAY_TASK_ID.stdout 2>watcher_$SLURM_ARRAY_TASK_ID.stderr &

trap 'sig_handler' SIGUSR1

# execute simulation
srun shieldhit -N $RNG_SEED $WORK_DIR &

wait
"""  # skipcq: FLK-E501
