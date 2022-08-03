#!/bin/bash
#SBATCH --nodes 1
#SBATCH --ntasks 1
#SBATCH --time=00:04:59
#SBATCH -A plgccbmc11-cpu

SCRATCH_DIRECTORY=/net/pr2/scratch/people/${USER}/${SLURM_JOBID}
mkdir -p ${SCRATCH_DIRECTORY}
cd ${SCRATCH_DIRECTORY}

cp ${SLURM_SUBMIT_DIR}/sh_inputs/beam.dat ${SCRATCH_DIRECTORY}
cp ${SLURM_SUBMIT_DIR}/sh_inputs/detect.dat ${SCRATCH_DIRECTORY}
cp ${SLURM_SUBMIT_DIR}/sh_inputs/geo.dat ${SCRATCH_DIRECTORY}
cp ${SLURM_SUBMIT_DIR}/sh_inputs/mat.dat ${SCRATCH_DIRECTORY}

module load gcc/11.3.0
export PATH=$PATH:$PLG_GROUPS_STORAGE/plggyaptide
shieldhit

mkdir -p ${SLURM_SUBMIT_DIR}/sh_output/${SLURM_JOBID}
cp *.bdo ${SLURM_SUBMIT_DIR}/sh_output/${SLURM_JOBID}

cd ${SLURM_SUBMIT_DIR}
rm -rf ${SCRATCH_DIRECTORY}

exit 0