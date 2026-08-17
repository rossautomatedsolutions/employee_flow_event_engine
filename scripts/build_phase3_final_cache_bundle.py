from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.reproducibility.phase3_final_bundle import build_portable_bundle, default_bundle_paths


def _parse_args() -> argparse.Namespace:
    paths = default_bundle_paths()
    parser = argparse.ArgumentParser(description="Build the portable SEC cache bundle for the final 33-issuer discovery replay.")
    parser.add_argument("--repo-root", type=Path, default=paths.repo_root, help="Repository root containing the authoritative cache.")
    parser.add_argument("--cache-dir", type=Path, default=paths.cache_dir, help="Authoritative cache directory to package.")
    parser.add_argument("--bundle-path", type=Path, default=paths.bundle_path, help="Output .tar.gz bundle path.")
    parser.add_argument("--manifest-path", type=Path, default=paths.manifest_path, help="Output JSON manifest path.")
    parser.add_argument("--config-path", type=Path, default=paths.config_path, help="Final cache-only config to audit against.")
    parser.add_argument("--review-file", type=Path, default=paths.review_file, help="Tracked review decisions CSV.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    manifest = build_portable_bundle(
        repo_root=args.repo_root,
        cache_dir=args.cache_dir,
        bundle_path=args.bundle_path,
        manifest_path=args.manifest_path,
        config_path=args.config_path,
        review_file=args.review_file,
    )
    print(json.dumps(
        {
            "bundle_file": manifest["bundle_file"],
            "bundle_size_bytes": manifest["bundle_size_bytes"],
            "bundle_sha256": manifest["bundle_sha256"],
            "cache_summary": manifest["cache_summary"],
            "expected_result": manifest["expected_result"],
        },
        indent=2,
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
