from yaptide.batch.utils.utils import sanitize_string


def test_removes_shell_metacharacters_keeps_whitespace():
    """Shell operators are stripped, whitespace between words stays"""
    assert sanitize_string("4G && echo pwn") == "4G  echo pwn"


def test_removes_substitution_and_quotes():
    """Command substitution and quoting characters are stripped"""
    assert sanitize_string("plg-cpu; $(id) `x` 'y' \"z\"") == "plg-cpu id x y z"


def test_passes_safe_values_unchanged():
    """Values made of allowed characters are returned as they are"""
    assert sanitize_string("00:59:59") == "00:59:59"
    assert sanitize_string("/net/scratch/run/aggregator.log") == "/net/scratch/run/aggregator.log"
    assert sanitize_string("yaptide_aggregator_42") == "yaptide_aggregator_42"


def test_removes_newlines_that_would_split_the_command_line():
    """A newline in an sbatch option value would start a new command in the submit script"""
    assert sanitize_string("plg-cpu\ntouch /tmp/x\r\n") == "plg-cputouch /tmp/x"


def test_header_keeps_newlines():
    """The sbatch header is a multi-line block"""
    assert sanitize_string("#SBATCH --time=1\n#SBATCH --qos=x", r"\s\w\-.,=/:#") == "#SBATCH --time=1\n#SBATCH --qos=x"


def test_custom_allowed_chars_hash():
    """Extra allowed characters extend the default set"""
    assert sanitize_string("#SBATCH --time=00:59:59", r"\w\-.,=/:# ") == "#SBATCH --time=00:59:59"
    assert sanitize_string("#SBATCH --time=00:59:59") == "SBATCH --time=00:59:59"
