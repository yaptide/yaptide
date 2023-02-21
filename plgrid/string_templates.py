SHIELDHIT_BASH: str = """#!/bin/bash
#SBATCH --ntasks 1
#SBATCH --time=00:04:59
#SBATCH -A plgccbmc11-cpu

JOB_ID=$(printenv | grep -Po '(?<=^SLURM_JOBID=)\\w*$')
SUBMIT_DIR=$(pwd)
WORKSPACE=${{SCRATCH}}/${{JOB_ID}}
mkdir -p ${{WORKSPACE}}
cd ${{WORKSPACE}}

BEAM_FILE=${{WORKSPACE}}/beam.dat
GEO_FILE=${{WORKSPACE}}/geo.dat
MAT_FILE=${{WORKSPACE}}/mat.dat
DETECT_FILE=${{WORKSPACE}}/detect.dat

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
rm -rf ${{WORKSPACE}}

exit 0
"""  # skipcq: FLK-E501

# as for now we hardcode that the results are being saved in home directory
PLGDATA_LIST_URL: str = """{http_plgdata}/list/{hostname}/~/sh_output/{slurm_job_id}"""

PLGDATA_GET_URL: str = """{http_plgdata}/download/{hostname}/~/sh_output/{slurm_job_id}/{filename}"""  # skipcq: FLK-E501
