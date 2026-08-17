from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.reproducibility.phase3_final_bundle import default_bundle_paths, restore_portable_bundle


def _parse_args() -> argparse.Namespace:
    paths = default_bundle_paths()
    parser = argparse.ArgumentParser(description="Restore the portable SEC cache bundle for the final 33-issuer discovery replay.")
    parser.add_argument("--repo-root", type=Path, default=paths.repo_root, help="Repository root to restore into.")
    parser.add_argument("--bundle-path", type=Path, default=paths.bundle_path, help="Tracked .tar.gz bundle path.")
    parser.add_argument("--manifest-path", type=Path, default=paths.manifest_path, help="Tracked JSON manifest path.")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Delete an existing cache directory at the restore target instead of backing it up before restore.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = restore_portable_bundle(
        repo_root=args.repo_root,
        bundle_path=args.bundle_path,
        manifest_path=args.manifest_path,
        overwrite=args.overwrite,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
