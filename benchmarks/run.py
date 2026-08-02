"""Benchmark Harness Entrypoint (LLD 41 §4.8)."""

from benchmarks.core.isolation import enforce

# FIRST executable statement: enforce isolation chain I1-I5
enforce()

import sys
from benchmarks.core.config import parse_cli_args
from benchmarks.core.registry import get_adapter


def main() -> int:
    config = parse_cli_args()
    try:
        adapter = get_adapter(config.adapter)
    except KeyError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 2
    
    print(f"Loaded benchmark adapter: {adapter.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
