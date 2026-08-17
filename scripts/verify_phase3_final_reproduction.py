from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.reproducibility.phase3_final_bundle import default_bundle_paths, run_verified_reproduction


def _parse_args() -> argparse.Namespace:
    paths = default_bundle_paths()
    parser = argparse.ArgumentParser(description="Run the final cache-only 33-issuer replay and assert the expected reviewed result.")
    parser.add_argument("--repo-root", type=Path, default=paths.repo_root, help="Repository root containing the config and bundle.")
    parser.add_argument("--config-path", type=Path, default=paths.config_path, help="Final cache-only config to execute.")
    parser.add_argument("--cache-dir", type=Path, default=None, help="Optional cache-dir override for temporary validation runs.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Optional output-dir override for temporary validation runs.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    summary = run_verified_reproduction(
        repo_root=args.repo_root,
        config_path=args.config_path,
        cache_dir=args.cache_dir,
        output_dir=args.output_dir,
        force=True,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
