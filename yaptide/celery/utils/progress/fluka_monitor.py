import re
from typing import Optional, Tuple

# templates for regex matching output from `<simulation>_<no>.err` file
S_OK_OUT_INIT = re.compile(r"^ Total time used for initialization:")
S_OK_OUT_START = re.compile(r"^1NUMBER OF BEAM")
S_OK_OUT_IN_PROGRESS = re.compile(r"^ NEXT SEEDS:")
S_OK_OUT_COLLECTED = re.compile(r"^ All cases handled by Feeder")
S_OK_OUT_FIN = re.compile(r"^ \* ======(?:( )*?)End of FLUKA [\w\-.]* run (?:( )*?) ====== \*")

# for larger number of particles values are shifted accordingly to fit all digits, e.g. for 1e+12 particles:
# "              1          999999999999          999999999999         2.8598309E-04         1.0000000E+30                 0       "
S_OK_OUT_PROGRESS_REMAINING_LINE_EXAMPLE = \
    "     980000                 20000                 20000             1.8515483E-04         1.0000000E+30             44182       "


def parse_progress_remaining_line(line: str) -> Optional[Tuple[int, int]]:
    """Function parsing the line with progress remaining information.

    Args:
        line (str): line to be parsed
    Returns:
        Tuple[int, int]: tuple with two integers representing the progress and remaining.
        If the line cannot be parsed None is returned.
    """
    list = line.split()
    # expecting 6 sections which are int or floats
    if len(list) != 6:
        return None
    try:
        [float(x) for x in list]
    except ValueError:
        return None
    return (int(list[0]), int(list[1]))
