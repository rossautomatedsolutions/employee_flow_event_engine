from __future__ import annotations

import argparse
from pathlib import Path

from src.pipeline.run_event_study import run_first_pass_event_study


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ESPP strategy hypothesis testing experiment")
    parser.add_argument("--config", type=Path, default=Path("config/example.yaml"), help="Path to YAML experiment config")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_first_pass_event_study(config_path=args.config)
