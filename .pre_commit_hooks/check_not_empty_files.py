"""Check that files are not empty."""

from __future__ import annotations

import argparse
import os
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Check that files are not empty."""
    parser = argparse.ArgumentParser()
    parser.add_argument('filenames', nargs='*', help='Filenames to check.')
    args = parser.parse_args(argv)

    for filename in args.filenames:
        if os.stat(filename).st_size > 0:
            print(f'{filename} is not empty')
            return 1

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
