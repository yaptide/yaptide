import re


def sanitize_string(target_str: str, allowed_chars: str = r"\w\-.,=/:") -> str:
    """Function clearing unaccepted signs"""
    return re.sub(f"[^\\s{allowed_chars}]", "", target_str)


def extract_sbatch_header(payload_dict: dict, target_key: str) -> str:
    """Function extracting header for slurm script"""
    return (
        sanitize_string(payload_dict["batch_options"][target_key], r"\w\-.,=/:#")
        if "batch_options" in payload_dict and target_key in payload_dict["batch_options"]
        else ""
    )


def convert_dict_to_sbatch_options(payload_dict: dict, target_key: str) -> str:
    """Function converting dict to sbatch command line options"""
    options_dict = {"time": "00:59:59"}
    if "batch_options" in payload_dict and target_key in payload_dict["batch_options"]:
        options_dict.update(payload_dict["batch_options"][target_key])
    opt_list = []
    for key, val in options_dict.items():
        opt_list.append(f"--{sanitize_string(key)}={sanitize_string(val)}")
    return " ".join(opt_list)


# resources of the array job say nothing about the aggregator, its accounting does
AGGREGATOR_IGNORED_ARRAY_OPTIONS = {
    "array",
    "nodes",
    "ntasks",
    "ntasks-per-node",
    "ntasks-per-core",
    "cpus-per-task",
    "mem",
    "mem-per-cpu",
    "gres",
    "gpus",
    "job-name",
    "output",
    "error",
}


def convert_dict_to_aggregator_sbatch_options(payload_dict: dict, sim_id: int, job_dir: str) -> str:
    """Function building sbatch options for the aggregator job

    It keeps whatever the array job needs to be accepted by the queue (account, partition, time, qos)
    and asks for a single cheap cpu, because the aggregator only forwards updates.
    """
    options_dict = {"time": "00:59:59"}
    array_options = payload_dict.get("batch_options", {}).get("array_options", {})
    options_dict.update({key: val for key, val in array_options.items() if key not in AGGREGATOR_IGNORED_ARRAY_OPTIONS})
    options_dict.update(
        {
            "ntasks": "1",
            "cpus-per-task": "1",
            "mem": "1G",
            "job-name": f"yaptide_aggregator_{sim_id}",
            "output": f"{job_dir}/aggregator.log",
        }
    )
    opt_list = []
    for key, val in options_dict.items():
        opt_list.append(f"--{sanitize_string(key)}={sanitize_string(str(val))}")
    return " ".join(opt_list)
