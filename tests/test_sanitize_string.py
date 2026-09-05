from yaptide.batch.utils.utils import sanitize_string


def test_removes_shell_metacharacters_keeps_whitespace():
    assert sanitize_string("4G && echo pwn") == "4G  echo pwn"


def test_removes_substitution_and_quotes():
    assert sanitize_string("plg-cpu; $(id) `x` 'y' \"z\"") == "plg-cpu id x y z"


def test_passes_safe_values_unchanged():
    assert sanitize_string("00:59:59") == "00:59:59"
    assert sanitize_string("/net/scratch/run/aggregator.log") == "/net/scratch/run/aggregator.log"
    assert sanitize_string("yaptide_aggregator_42") == "yaptide_aggregator_42"


def test_custom_allowed_chars_hash():
    assert sanitize_string("#SBATCH --time=00:59:59", r"\w\-.,=/:#") == "#SBATCH --time=00:59:59"
    assert sanitize_string("#SBATCH --time=00:59:59") == "SBATCH --time=00:59:59"
