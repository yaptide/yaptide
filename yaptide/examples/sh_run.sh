#!/bin/bash
#SBATCH --nodes 1
#SBATCH --ntasks 1
#SBATCH --time=00:00:59
#SBATCH -A plgccbmc11-cpu

printenv | grep 'SLURM_JOBID'
echo ${USER}
# echo ${SLURM_JOBID}

exit 0