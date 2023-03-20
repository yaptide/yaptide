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

SHIELDHIT_CMD="sbatch --array=1-{n_tasks} --time=00:04:59 -A plgccbmc11-cpu --partition=plgrid-testing --parsable $ARRAY_SCRIPT > $OUT"
eval $SHIELDHIT_CMD
JOB_ID=`cat $OUT | cut -d ";" -f 1`
echo "Job id: $JOB_ID"

if [ -n "$JOB_ID" ] ; then
    COLLECT_CMD="sbatch --dependency=afterany:$JOB_ID --time=00:00:59 -A plgccbmc11-cpu --partition=plgrid-testing --parsable $COLLECT_SCRIPT > $OUT"
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

# go to working directory
cd $WORK_DIR
pwd

sig_handler()
{{
    echo "BATCH interrupted"
    wait # wait for all children, this is important!
}}

trap 'sig_handler' SIGUSR1

# execute simulation
srun shieldhit --beamfile=$BEAM_FILE --geofile=$GEO_FILE --matfile=$MAT_FILE --detectfile=$DETECT_FILE -n {particle_no} -N $RNG_SEED  $WORK_DIR
"""  # skipcq: FLK-E501
