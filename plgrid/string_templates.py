shieldhit_bash: str = """#!/bin/bash
#SBATCH --nodes 1
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

plgdata_list_url: str = """{http_plgdata}/list/{hostname}/net/people/{plguserlogin}/sh_output/{job_id}"""

plgdata_get_url: str = """{http_plgdata}/download/{hostname}/net/people/{plguserlogin}/sh_output/{job_id}/{filename}"""  # skipcq: FLK-E501
