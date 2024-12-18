SUBMIT_FLUKA: str = """#!/bin/bash
OUT=`mktemp`

# Path to rfluka
FLUTIL_PATH=$SCRATCH/fluka/flutil
RFLUKA=$FLUTIL_PATH/rfluka

# Directory setup
ROOT_DIR=$SCRATCH/fluka_job
#cd $ROOT_DIR
#mkdir -p $ROOT_DIR/workspaces/task_{{0001..5}}
#mkdir -p $ROOT_DIR/input

INPUT_DIR=$ROOT_DIR/input
WORKSPACES_DIR=$ROOT_DIR/workspaces
ARRAY_SCRIPT=$ROOT_DIR/array_script.sh
COLLECT_SCRIPT=$ROOT_DIR/collect_script.sh

#unzip -d $INPUT_DIR $ROOT_DIR/input.zip
#rm $ROOT_DIR/input.zip

# Create necessary directories
mkdir -p $ROOT_DIR/logs $INPUT_DIR $WORKSPACES_DIR/task_{0001..0005} $ROOT_DIR/output

# Submit array job
OUT=$(mktemp)
sbatch --array=1-5 --time=00:15:00 --mem=4G $ARRAY_SCRIPT > $OUT
ARRAY_JOB_ID=$(cat $OUT | awk '{print $NF}')

# Submit collect job after array job completes
if [ -n "$ARRAY_JOB_ID" ]; then
    sbatch --dependency=afterany:$ARRAY_JOB_ID --time=01:00:00 --mem=2G $COLLECT_SCRIPT
fi
"""

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

SHIELDHIT_CMD="sbatch --array=1-{n_tasks} {array_options} --parsable $ARRAY_SCRIPT > $OUT"
eval $SHIELDHIT_CMD
JOB_ID=`cat $OUT | cut -d ";" -f 1`
echo "Job id: $JOB_ID"

if [ -n "$JOB_ID" ] ; then
    COLLECT_CMD="sbatch --dependency=afterany:$JOB_ID {collect_options} --parsable $COLLECT_SCRIPT > $OUT"
    eval $COLLECT_CMD
    COLLECT_ID=`cat $OUT | cut -d ";" -f 1`
    echo "Collect id: $COLLECT_ID"
fi
"""  # skipcq: FLK-E501

COLLECT_BASH: str = """#!/bin/bash
#SBATCH --job-name=fluka_collect
#SBATCH --output=logs/collect_%j.log
#SBATCH --time=01:00:00
#SBATCH --mem=2G

ROOT_DIR=$SCRATCH/fluka_job


INPUT_WILDCARD48=$ROOT_DIR/workspaces/task_*/*_fort.48
INPUT_WILDCARD49=$ROOT_DIR/workspaces/task_*/*_fort.49
INPUT_WILDCARD50=$ROOT_DIR/workspaces/task_*/*_fort.50
INPUT_WILDCARD51=$ROOT_DIR/workspaces/task_*/*_fort.51
OUTPUT_DIRECTORY=$ROOT_DIR/output

echo $INPUT_WILDCARD

# Create output directory
mkdir -p $OUTPUT_DIR

cd $OUTPUT_DIRECTORY

convertmc json --many "$INPUT_WILDCARD48"
convertmc json --many "$INPUT_WILDCARD49"
convertmc json --many "$INPUT_WILDCARD50"
convertmc json --many "$INPUT_WILDCARD51"

# Optional cleanup
#rm -r $ROOT_DIR/workspaces/task_*
"""

COLLECT_BASH: str = """#!/bin/bash
{collect_header}
ROOT_DIR={root_dir}
python3 $ROOT_DIR/simulation_data_sender.py --sim_id={sim_id} --update_key={update_key} \\
      --backend_url={backend_url} --simulation_state=MERGING_RUNNING

INPUT_WILDCARD=$ROOT_DIR/workspaces/task_*/*.bdo
OUTPUT_DIRECTORY=$ROOT_DIR/output

mkdir -p $OUTPUT_DIRECTORY

cd $OUTPUT_DIRECTORY

convertmc json --many "$INPUT_WILDCARD"

CLEAR_BDOS={clear_bdos}

if $CLEAR_BDOS; then
    rm $INPUT_WILDCARD
fi

python3 $ROOT_DIR/simulation_data_sender.py --output_dir=$OUTPUT_DIRECTORY \\
    --sim_id={sim_id} --update_key={update_key} --backend_url={backend_url}
"""  # skipcq: FLK-E501

ARRAY_FLUKA_BASH: str = """#!/bin/bash
#SBATCH --job-name=fluka_array
#SBATCH --output=logs/array_%A_%a.log
#SBATCH --time=02:00:00
#SBATCH --mem=4G

# Path to rfluka
FLUTIL_PATH=$SCRATCH/fluka/flutil
RFLUKA=$FLUTIL_PATH/rfluka

# Directories
ROOT_DIR=$SCRATCH/fluka_job
WORK_DIR=$ROOT_DIR/workspaces/task_`printf %04d $SLURM_ARRAY_TASK_ID`
INPUT_DIR=$ROOT_DIR/input

# seed of RNG
RNG_SEED=$SLURM_ARRAY_TASK_ID

# Set up working directory
#mkdir -p $WORK_DIR
cd $WORK_DIR

# Copy the input file into the workspace
INPUT_FILE=example.inp
#cp $INPUT_DIR/$INPUT_FILE $WORK_DIR

# make symbolic links to all files from input folder
ln -s $INPUT_DIR/* .

#sig_handler()
#{{
#    echo "BATCH interrupted"
#    wait # wait for all children, this is important!
#}}

trap 'sig_handler' SIGUSR1

# Run FLUKA simulation
srun $RFLUKA -N0 -M1 $INPUT_FILE &

wait
"""

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
    --verbose 1>watcher_$SLURM_ARRAY_TASK_ID.stdout 2>watcher_$SLURM_ARRAY_TASK_ID.stderr &

trap 'sig_handler' SIGUSR1

# execute simulation
srun shieldhit -N $RNG_SEED $WORK_DIR &

wait
"""  # skipcq: FLK-E501
