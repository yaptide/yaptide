SUBMIT_SHIELDHIT: str = """#!/bin/bash
OUT=`mktemp`
module load shieldhit
module load pyzmq/25.1.2-gcccore-13.2.0

ROOT_DIR={root_dir}
cd $ROOT_DIR
mkdir -p $ROOT_DIR/workspaces/task_{{0001..{n_tasks}}}
mkdir -p $ROOT_DIR/input


INPUT_DIR=$ROOT_DIR/input
ARRAY_SCRIPT=$ROOT_DIR/array_script.sh
COLLECT_SCRIPT=$ROOT_DIR/collect_script.sh
AGGREGATOR_SCRIPT=$ROOT_DIR/aggregator_script.sh

unzip -d $INPUT_DIR $ROOT_DIR/input.zip
rm $ROOT_DIR/input.zip

SHIELDHIT_CMD="sbatch --array=1-{n_tasks} {array_options} --parsable $ARRAY_SCRIPT > $OUT"
eval $SHIELDHIT_CMD
JOB_ID=`cat $OUT | cut -d ";" -f 1`
echo "Job id: $JOB_ID"
# every job id goes next to the jobs as well, so a cancel finds them even if the submit was interrupted
echo "$JOB_ID" > $ROOT_DIR/array_job_id

if [ -n "$JOB_ID" ] ; then
    # the aggregator batches the progress updates of all tasks into single requests to the backend
    # it gets its own small allocation, so nothing runs on the login node; it becomes eligible once the first task
    # started (a dependency on the whole array waits for the LAST one), starting takes up to a scheduler cycle more -
    # until then, and after it reaches its time limit (it inherits the time of the array tasks), the watchers report
    # through the throttled REST fallback, so tasks that start later than that are still tracked
    AGGREGATOR_OPTS="--dependency=after:${{JOB_ID}}_1 {aggregator_options}"
    AGGREGATOR_CMD="sbatch $AGGREGATOR_OPTS --parsable $AGGREGATOR_SCRIPT > $OUT"
    eval $AGGREGATOR_CMD
    AGGREGATOR_ID=`cat $OUT | cut -d ";" -f 1`
    echo "Aggregator id: $AGGREGATOR_ID"
    # the collect job and job deletion stop the aggregator by this id
    if [ -n "$AGGREGATOR_ID" ] ; then
        echo "$AGGREGATOR_ID" > $ROOT_DIR/aggregator_job_id
    fi

    COLLECT_CMD="sbatch --dependency=afterany:$JOB_ID {collect_options} --parsable $COLLECT_SCRIPT > $OUT"
    eval $COLLECT_CMD
    COLLECT_ID=`cat $OUT | cut -d ";" -f 1`
    echo "Collect id: $COLLECT_ID"
    echo "$COLLECT_ID" > $ROOT_DIR/collect_job_id
    # a collect job that SLURM stops (time limit, memory, node failure, scancel) cannot report it ended, so a small
    # job does it then; it is removed by SLURM when the collect succeeds (--kill-on-invalid-dep)
    if [ -n "$COLLECT_ID" ] ; then
        REPORTER_OPTS="--dependency=afternotok:$COLLECT_ID --kill-on-invalid-dep=yes {reporter_options} --parsable"
        REPORTER_SEND="python3 $ROOT_DIR/simulation_data_sender.py --sim_id={sim_id} --update_key={update_key}"
        REPORTER_SEND="$REPORTER_SEND --backend_url={backend_url} --simulation_state=FAILED"
        REPORTER_CMD="sbatch $REPORTER_OPTS --wrap=\\"$REPORTER_SEND\\" > $OUT"
        eval $REPORTER_CMD
        REPORTER_ID=`cat $OUT | cut -d ";" -f 1`
        echo "Reporter id: $REPORTER_ID"
        if [ -n "$REPORTER_ID" ] ; then
            echo "$REPORTER_ID" > $ROOT_DIR/reporter_job_id
        fi
    fi
fi
"""  # skipcq: FLK-E501

COLLECT_SHIELDHIT_BASH: str = """#!/bin/bash
{collect_header}
ROOT_DIR={root_dir}
# every array task has ended - stop the aggregator (it flushes what it holds on SIGTERM), otherwise it would
# wait until its time limit whenever some task reported its final state straight to the backend
if [ -s $ROOT_DIR/aggregator_job_id ] ; then
    scancel `cat $ROOT_DIR/aggregator_job_id`
fi
python3 $ROOT_DIR/simulation_data_sender.py --sim_id={sim_id} --update_key={update_key} \\
      --backend_url={backend_url} --simulation_state=MERGING_RUNNING

INPUT_WILDCARD=$ROOT_DIR/workspaces/task_*/*.bdo
OUTPUT_DIRECTORY=$ROOT_DIR/output

mkdir -p $OUTPUT_DIRECTORY

cd $OUTPUT_DIRECTORY

if ! convertmc json --many "$INPUT_WILDCARD" || [ -z "$(ls $OUTPUT_DIRECTORY/*.json 2>/dev/null)" ] ; then
    # nothing to merge (every task failed) or unreadable task outputs - without this the job would end as completed
    # with empty results; task outputs are kept for a manual look
    python3 $ROOT_DIR/simulation_data_sender.py --sim_id={sim_id} --update_key={update_key} \\
          --backend_url={backend_url} --simulation_state=FAILED
    exit 1
fi

CLEAR_BDOS={remove_output_from_workspace}

if $CLEAR_BDOS; then
    rm $INPUT_WILDCARD
fi

# the pages go straight to the storage of the backend; a failed upload fails the job, the reporter job reports it
python3 $ROOT_DIR/results_uploader.py --output_dir=$OUTPUT_DIRECTORY \\
    --sim_id={sim_id} --update_key={update_key} --backend_url={backend_url} || exit 1
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

AGGREGATOR_SHIELDHIT_BASH: str = """#!/bin/bash
{aggregator_header}
ROOT_DIR={root_dir}
# exec, so the SIGTERM slurm sends at the time limit reaches the aggregator itself and it can flush what it holds
exec python3 $ROOT_DIR/aggregator.py --sim_id={sim_id} --update_key={update_key} \\
    --backend_url={backend_url} --root_dir=$ROOT_DIR --ntasks={n_tasks}
"""  # skipcq: FLK-E501
