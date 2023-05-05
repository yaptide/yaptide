import re


def sanitize_string(target_str: str, allowed_chars: str = r'[\w\-.,=/:]+') -> str:
    """Function clearing unaccepted signs"""
    return re.sub(f'[^\\s{allowed_chars}]', '', target_str)


def extract_sbatch_header(payload_dict: dict, target_key: str) -> str:
    """Function extracting header for slurm script"""
    return (sanitize_string(payload_dict["batch_options"][target_key], r'[\w\-.,=/:#]+')
            if "batch_options" in payload_dict
            and target_key in payload_dict["batch_options"]
            else "")


def convert_dict_to_sbatch_options(payload_dict: dict, target_key: str) -> str:
    """Function converting dict to sbatch command line options"""
    options_dict = {
        "time": "00:59:59"
    }
    if "batch_options" in payload_dict and target_key in payload_dict["batch_options"]:
        options_dict.update(payload_dict["batch_options"][target_key])
    opt_list = []
    for key, val in options_dict.items():
        opt_list.append(f"--{sanitize_string(key)}={sanitize_string(val)}")
    return " ".join(opt_list)
