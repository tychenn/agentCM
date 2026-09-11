"""Run the CLI from a source checkout without installing the package."""
import sys
from pathlib import Path


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
    from trajectory_graph.cli import main

    raise SystemExit(main())
