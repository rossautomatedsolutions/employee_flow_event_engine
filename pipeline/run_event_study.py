from __future__ import annotations

import argparse
from pathlib import Path

from src.pipeline.run_event_study import run_first_pass_event_study


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run first-pass ESPP event study experiment")
    parser.add_argument("--years", type=int, default=5, help="Price history length in years (bounded to 2..5)")
    parser.add_argument("--benchmark", type=str, default="SPY", help="Benchmark ticker for abnormal returns")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/first_pass"), help="Output directory")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_first_pass_event_study(years=args.years, output_dir=args.output_dir, benchmark=args.benchmark)
