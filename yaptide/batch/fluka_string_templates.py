SUBMIT_FLUKA: str = """#!/bin/bash
OUT=`mktemp`
module load fluka

ROOT_DIR={root_dir}
cd $ROOT_DIR
mkdir -p $ROOT_DIR/workspaces/task_{{0001..{n_tasks}}}
mkdir -p $ROOT_DIR/input $ROOT_DIR/done

INPUT_DIR=$ROOT_DIR/input
ARRAY_SCRIPT=$ROOT_DIR/array_script.sh
COLLECT_SCRIPT=$ROOT_DIR/collect_script.sh

unzip -d $INPUT_DIR $ROOT_DIR/input.zip
rm $ROOT_DIR/input.zip

FLUKA_CMD="sbatch --array=1-{n_tasks} {array_options} --parsable $ARRAY_SCRIPT > $OUT"
eval $FLUKA_CMD
JOB_ID=`cat $OUT | cut -d ";" -f 1`
echo "Job id: $JOB_ID"
# every job id goes next to the jobs as well, so a cancel finds them even if the submit was interrupted
echo "$JOB_ID" > $ROOT_DIR/array_job_id

if [ -n "$JOB_ID" ] ; then
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

COLLECT_FLUKA_BASH: str = """#!/bin/bash
{collect_header}
ROOT_DIR={root_dir}
# the last array task runs this script already (as "inline"); this job, started after the whole array, collects only
# when that did not succeed: a task that did not end, a failure, or the task's time or memory limit
if [ -e $ROOT_DIR/collected ] ; then
    exit 0
fi

INPUT_WILDCARD="$ROOT_DIR/workspaces/task_*/*_fort.*"
OUTPUT_DIRECTORY=$ROOT_DIR/output

mkdir -p $OUTPUT_DIRECTORY

cd $OUTPUT_DIRECTORY

python3 $ROOT_DIR/simulation_data_sender.py --sim_id={sim_id} --update_key={update_key} \\
      --backend_url={backend_url} --simulation_state=MERGING_RUNNING

module load pymchelper
if ! convertmc json --many "$INPUT_WILDCARD" || [ -z "$(ls $OUTPUT_DIRECTORY/*.json 2>/dev/null)" ] ; then
    # nothing to merge (every task failed) or unreadable task outputs - without this the job would end as completed
    # with empty results; task outputs are kept for a manual look. A failure inline may be the task's memory limit,
    # this job tries again and reports it
    if [ "$1" != inline ] ; then
        python3 $ROOT_DIR/simulation_data_sender.py --sim_id={sim_id} --update_key={update_key} \\
              --backend_url={backend_url} --simulation_state=FAILED
    fi
    exit 1
fi

# the pages go straight to the storage of the backend; a failed upload fails the job, the reporter job reports it
python3 $ROOT_DIR/results_uploader.py --output_dir=$OUTPUT_DIRECTORY \\
    --sim_id={sim_id} --update_key={update_key} --backend_url={backend_url} || exit 1
touch $ROOT_DIR/collected

CLEAR_FORTS={remove_output_from_workspace}

# find, as thousands of task outputs pass the argument limit of rm
if $CLEAR_FORTS; then
    find $ROOT_DIR/workspaces -name "*_fort.*" -delete || true
fi

python3 $ROOT_DIR/simulation_data_sender.py --sim_id={sim_id} --update_key={update_key} \\
      --backend_url={backend_url} --simulation_state=COMPLETED
"""

ARRAY_FLUKA_BASH: str = """#!/bin/bash
{array_header}
ROOT_DIR={root_dir}
WORK_DIR=$ROOT_DIR/workspaces/task_`printf %04d $SLURM_ARRAY_TASK_ID`

# seed of RNG
RNG_SEED=$SLURM_ARRAY_TASK_ID

# main FLUKA input files
INPUT_DIR=$ROOT_DIR/input

# go to working directory
cd $WORK_DIR

# copy .inp file from input folder to working directory
cp $INPUT_DIR/*.inp .

# assign .inp file to a variable
INPUT_FILE=$(ls *.inp)

module load pymchelper
python3 -c "from pymchelper.executor.runner import Runner;Runner._Runner__update_fluka_input_file('${{INPUT_FILE}}',${{RNG_SEED}}.0)" # noqa: E501
sig_handler()
{{
    echo "BATCH interrupted"
    wait # wait for all children, this is important!
}}

trap 'sig_handler' SIGUSR1

# execute simulation
srun rfluka -N0 -M1 $WORK_DIR/*.inp &
SIMULATOR_PID=$!

# reports the progress into storage and stops the simulator when the simulation is cancelled
python3 $ROOT_DIR/watcher.py --simulator=fluka --work_dir=$WORK_DIR --pid=$SIMULATOR_PID \\
    --links=$ROOT_DIR/storage_links.json --ntasks={n_tasks} --sim_id={sim_id} --task_id=$SLURM_ARRAY_TASK_ID \\
    --backend_url={backend_url} \\
    1>watcher_$SLURM_ARRAY_TASK_ID.stdout 2>watcher_$SLURM_ARRAY_TASK_ID.stderr &

wait

# the last task to end merges and uploads the results at once: the collect job, queued after the whole array, waits
# minutes for a node; it collects only when this did not happen or failed
touch $ROOT_DIR/done/task_$SLURM_ARRAY_TASK_ID
if [ `ls $ROOT_DIR/done | wc -l` -eq {n_tasks} ] && mkdir $ROOT_DIR/collect.lock 2>/dev/null ; then
    bash $ROOT_DIR/collect_script.sh inline || echo "Collect left to the collect job"
fi
"""
