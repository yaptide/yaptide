import re


# @ % + [ ] appear in valid sbatch values: --mail-user=a@b.pl, --output=%x_%j.out, --signal=USR1@60,
# --begin=now+1hour, --nodelist=ac[0001-0004]; none of them can start a command or end a quoted string
def sanitize_string(target_str: str, allowed_chars: str = r"\w\-.,=/: @%+\[\]") -> str:
    """Function clearing unaccepted signs - by default also newlines, which would split the sbatch command line"""
    return re.sub(f"[^{allowed_chars}]", "", target_str)


def extract_sbatch_header(payload_dict: dict, target_key: str) -> str:
    """Function extracting header for slurm script"""
    return (
        sanitize_string(payload_dict["batch_options"][target_key], r"\s\w\-.,=/:#@%+\[\]")
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


# only the queue placement and the time limit of the array job apply to the reporter job, never its resources -
# the UI lets users type any sbatch option (exclusive, constraint, nodelist...), so this is an allowlist;
# a --time in the array header is overridden for the array too by the --time on the command line
HELPER_INHERITED_ARRAY_OPTIONS = {"account", "partition", "qos", "time", "reservation"}


def queue_placement_options(array_header: str) -> list[str]:
    """Queue placement options typed as #SBATCH lines of the array header - the reporter job has to land in the
    same account and partition
    """
    # matches the long and short sbatch forms, with "=" or a space:
    #   --account=plgccbmc15-cpu   --partition plgrid   --qos=normal   --reservation=demo
    #   -A plgccbmc15-cpu   -p plgrid   -pplgrid   -q normal
    # and skips everything else, e.g. --time=02:00:00, --mem=4G, -N 1 or --exclusive
    placement = re.compile(r"(?<!\S)(--(?:account|partition|qos|reservation)(?:=|\s+)\S+|-[Apq]\s*\S+)")
    options = []
    for line in array_header.splitlines():
        # like sbatch: only lines starting with #SBATCH in the first column, anything after the next # is a comment
        if line.startswith("#SBATCH"):
            options.extend(placement.findall(line[len("#SBATCH") :].split("#", 1)[0]))
    return options


def helper_job_sbatch_options(
    payload_dict: dict, sim_id: int, job_dir: str, job_tag: str, role: str = "reporter"
) -> str:
    """sbatch command line options of a small helper job (the reporter of a failed collect)

    It keeps whatever the array job needs to be accepted by the queue (account, partition, qos, reservation, time),
    from the array's header and options - the options last, as they win - and asks for a single cheap cpu. It has the
    comment of the other jobs of the submit, which a cancel finds them by.
    """
    array_header = extract_sbatch_header(payload_dict=payload_dict, target_key="array_header")
    options_dict = {"time": "00:59:59"}
    array_options = payload_dict.get("batch_options", {}).get("array_options", {})
    options_dict.update({key: val for key, val in array_options.items() if key in HELPER_INHERITED_ARRAY_OPTIONS})
    options_dict.update(
        {
            "ntasks": "1",
            "cpus-per-task": "1",
            "mem": "1G",
            "job-name": f"yaptide_{role}_{sim_id}",
            "comment": job_tag,
            "output": f"{job_dir}/{role}.log",
        }
    )
    opt_list = [sanitize_string(option) for option in queue_placement_options(array_header)]
    for key, val in options_dict.items():
        opt_list.append(f"--{sanitize_string(key)}={sanitize_string(str(val))}")
    return " ".join(opt_list)
