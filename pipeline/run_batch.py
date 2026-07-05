from __future__ import annotations

import argparse
from pathlib import Path

from src.pipeline.run_batch import run_phase2_batch


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Phase 2 ESPP research batch pipeline")
    parser.add_argument("--config", type=Path, default=Path("config/phase2_example.yaml"), help="Path to YAML Phase 2 batch config")
    parser.add_argument("--force", action="store_true", help="Reprocess even previously completed companies")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_phase2_batch(config_path=args.config, force=bool(args.force))
