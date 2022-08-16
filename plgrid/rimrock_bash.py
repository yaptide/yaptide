shieldhit_bash: str = """#!/bin/bash
#SBATCH --nodes 1
#SBATCH --ntasks 1
#SBATCH --time=00:04:59
#SBATCH -A plgccbmc11-cpu

JOB_ID=$(printenv | grep -Po '(?<=^SLURM_JOBID=)\\w*$')
SUBMIT_DIR=$(pwd)
SCRATCH_DIRECTORY=/net/pr2/scratch/people/${{USER}}/${{JOB_ID}}
mkdir -p ${{SCRATCH_DIRECTORY}}
cd ${{SCRATCH_DIRECTORY}}

BEAM_FILE=${{SCRATCH_DIRECTORY}}/beam.dat
GEO_FILE=${{SCRATCH_DIRECTORY}}/geo.dat
MAT_FILE=${{SCRATCH_DIRECTORY}}/mat.dat
DETECT_FILE=${{SCRATCH_DIRECTORY}}/detect.dat

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

module load gcc/11.3.0
export PATH=$PATH:$PLG_GROUPS_STORAGE/plggyaptide
shieldhit

mkdir -p ${{SUBMIT_DIR}}/sh_output/${{JOB_ID}}
cp *.bdo ${{SUBMIT_DIR}}/sh_output/${{JOB_ID}}

cd ${{SUBMIT_DIR}}
rm -rf ${{SCRATCH_DIRECTORY}}

exit 0
"""  # skipcq: FLK-E501
