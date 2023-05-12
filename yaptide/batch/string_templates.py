SUBMIT_SHIELDHIT: str = """#!/bin/bash
OUT=`mktemp`
export PATH="$PATH:$PLG_GROUPS_STORAGE/plggccbmc"
module load gcc

ROOT_DIR={root_dir}
BIN_DIR=$ROOT_DIR/bin
cd $ROOT_DIR
mkdir -p $ROOT_DIR/workspaces/task_{{0001..{n_tasks}}}
mkdir -p $ROOT_DIR/input

CONVERTMC_VERSION={convertmc_version}

if [[ -f ${{BIN_DIR}}/convertmc ]]; then
    FOUND_VERSION=$($BIN_DIR/convertmc --version)
    if [ $FOUND_VERSION != $CONVERTMC_VERSION ]; then
        echo "Found old version of convertmc: $FOUND_VERSION"
        rm $BIN_DIR/convertmc
        wget -c -x -O $BIN_DIR/convertmc\\
            https://github.com/DataMedSci/pymchelper/releases/download/v$CONVERTMC_VERSION/convertmc
        chmod 750 $BIN_DIR/convertmc
    fi
else
    mkdir $BIN_DIR -p

    wget -c -x -O $BIN_DIR/convertmc\\
        https://github.com/DataMedSci/pymchelper/releases/download/v$CONVERTMC_VERSION/convertmc

    chmod 750 $BIN_DIR/convertmc
fi
echo "Using convertmc version: $CONVERTMC_VERSION"

INPUT_DIR=$ROOT_DIR/input
ARRAY_SCRIPT=$ROOT_DIR/array_script.sh
COLLECT_SCRIPT=$ROOT_DIR/collect_script.sh
SIGNAL_SCRIPT=$ROOT_DIR/signal_script.sh

unzip -d $INPUT_DIR $ROOT_DIR/input.zip
rm $ROOT_DIR/input.zip

SHIELDHIT_CMD="ROOT_DIR=${{ROOT_DIR}} BIN_DIR=${BIN_DIR} sbatch --array=1-{n_tasks} {array_options} --parsable $ARRAY_SCRIPT > $OUT"
eval $SHIELDHIT_CMD
JOB_ID=`cat $OUT | cut -d ";" -f 1`
echo "Job id: $JOB_ID"

if [ -n "$JOB_ID" ] ; then
    COLLECT_CMD="ROOT_DIR=${{ROOT_DIR}} BIN_DIR=${{BIN_DIR}} sbatch --dependency=afterany:$JOB_ID {collect_options} --parsable $COLLECT_SCRIPT > $OUT"
    eval $COLLECT_CMD
    COLLECT_ID=`cat $OUT | cut -d ";" -f 1`
    echo "Collect id: $COLLECT_ID"
    SIGNAL_ID=$JOB_ID ROOT_DIR=$ROOT_DIR sbatch --time=00:39:59 --account=plgccbmc11-cpu --partition=plgrid $SIGNAL_SCRIPT
fi
"""  # skipcq: FLK-E501

COLLECT_BASH: str = """#!/bin/bash
{collect_header}
INPUT_WILDCARD=$ROOT_DIR/workspaces/task_*/*.bdo
OUTPUT_DIRECTORY=$ROOT_DIR/output

mkdir -p $OUTPUT_DIRECTORY

cd $OUTPUT_DIRECTORY

$BIN_DIR/convertmc json --many "$INPUT_WILDCARD"

CLEAR_BDOS={clear_bdos}

if $CLEAR_BDOS; then
    rm $INPUT_WILDCARD
fi
"""  # skipcq: FLK-E501

ARRAY_SHIELDHIT_BASH: str = """#!/bin/bash
{array_header}
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
python3 $ROOT_DIR/watcher.py --workdir=$WORK_DIR --convertmc=$BIN_DIR/convertmc --filepath=$FILE_TO_WATCH\
    --job_id=$SLURM_JOB_ID --task_id=$SLURM_ARRAY_TASK_ID &

trap 'sig_handler' SIGUSR1

# execute simulation
srun shieldhit -N $RNG_SEED $WORK_DIR &

wait
"""  # skipcq: FLK-E501

SIGNAL_SCRIPT_BASH: str = """#!/bin/bash
#SBATCH --nodes 1
#SBATCH --ntasks 1
#SBATCH --mem=1GB

python3 $ROOT_DIR/analizer.py --root_dir=$ROOT_DIR --job_to_signal_id=$SIGNAL_ID 
"""
