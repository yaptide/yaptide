SUBMIT_FLUKA: str = """#!/bin/bash
OUT=`mktemp`
module load fluka

ROOT_DIR={root_dir}
cd $ROOT_DIR
mkdir -p $ROOT_DIR/workspaces/task_{{0001..{n_tasks}}}
mkdir -p $ROOT_DIR/input


INPUT_DIR=$ROOT_DIR/input
ARRAY_SCRIPT=$ROOT_DIR/array_script.sh
COLLECT_SCRIPT=$ROOT_DIR/collect_script.sh

unzip -d $INPUT_DIR $ROOT_DIR/input.zip
rm $ROOT_DIR/input.zip

FLUKA_CMD="sbatch --array=1-{n_tasks} {array_options} --parsable $ARRAY_SCRIPT > $OUT"
eval $FLUKA_CMD
JOB_ID=`cat $OUT | cut -d ";" -f 1`
echo "Job id: $JOB_ID"

if [ -n "$JOB_ID" ] ; then
    COLLECT_CMD="sbatch --dependency=afterany:$JOB_ID {collect_options} --parsable $COLLECT_SCRIPT > $OUT"
    eval $COLLECT_CMD
    COLLECT_ID=`cat $OUT | cut -d ";" -f 1`
    echo "Collect id: $COLLECT_ID"
fi
"""  # skipcq: FLK-E501

COLLECT_FLUKA_BASH: str = """#!/bin/bash
{collect_header}
ROOT_DIR={root_dir}

INPUT_WILDCARD="$ROOT_DIR/workspaces/task_*/*_fort.*"
OUTPUT_DIRECTORY=$ROOT_DIR/output

mkdir -p $OUTPUT_DIRECTORY

cd $OUTPUT_DIRECTORY

python3 $ROOT_DIR/simulation_data_sender.py --sim_id={sim_id} --update_key={update_key} \\
      --backend_url={backend_url} --simulation_state=MERGING_RUNNING

module load pymchelper
convertmc json --many "$INPUT_WILDCARD"

CLEAR_FORTS={clear_forts}

if $CLEAR_FORTS; then
    rm $INPUT_WILDCARD
fi

python3 $ROOT_DIR/simulation_data_sender.py --output_dir=$OUTPUT_DIRECTORY \\
    --sim_id={sim_id} --update_key={update_key} --backend_url={backend_url}
"""  # skipcq: FLK-E501

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
python3 -c "from pymchelper.executor.runner import Runner;Runner._Runner__update_fluka_input_file('\\''${{INPUT_FILE}}'\\'',${{RNG_SEED}}.0)"
sig_handler()
{{
    echo "BATCH interrupted"
    wait # wait for all children, this is important!
}}

FILE_TO_WATCH=$WORK_DIR/fluka_`printf %04d $SLURM_ARRAY_TASK_ID`.log
python3 $ROOT_DIR/watcher.py \
    --filepath=$FILE_TO_WATCH\
    --sim_id={sim_id}\
    --task_id=$SLURM_ARRAY_TASK_ID\
    --update_key={update_key}\
    --backend_url={backend_url}\
    --verbose 1>watcher_$SLURM_ARRAY_TASK_ID.stdout 2>watcher_$SLURM_ARRAY_TASK_ID.stderr &

trap 'sig_handler' SIGUSR1

# execute simulation
srun rfluka -N0 -M1 $WORK_DIR/*.inp &

wait
"""  # skipcq: FLK-E501
