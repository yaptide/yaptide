import re


def sanitize_string(target_str: str, allowed_chars: str = r'[\w\\-.,=/:]+') -> str:
    return re.sub(f'[^\\s{allowed_chars}]', '', target_str)


def extract_sbatch_header(json_data: dict, target_key: str) -> str:
    """Function used to clear unaccepted signs"""
    return (sanitize_string(json_data["batch_options"][target_key], r'[\w\\-.,=/:#]+')
            if "batch_options" in json_data
            and target_key in json_data["batch_options"]
            else "")


def convert_dict_to_sbatch_options(json_data: dict, target_key: str) -> str:
    """Function converting dict to sbatch command line options"""
    options_dict = {
        "time": "00:59:59",
        "account": "plgccbmc11-cpu",
        "partition": "plgrid"
    }
    if "batch_options" in json_data and target_key in json_data["batch_options"]:
        options_dict.update(json_data["batch_options"][target_key])
    opt_list = []
    for key, val in options_dict.items():
        opt_list.append(f"--{sanitize_string(key)}={sanitize_string(val)}")
    return " ".join(opt_list)
