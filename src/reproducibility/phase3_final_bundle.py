from __future__ import annotations

import csv
import gzip
import hashlib
import json
import shutil
import tarfile
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from src.pipeline.run_batch import run_phase2_batch

DEFAULT_CONFIG_PATH = Path("config/phase3_sec_discovery_sector33_20260817_final_reviewed_cache_only.yaml")
DEFAULT_CACHE_DIR = Path("artifacts/phase3_sec_discovery_sector33_20260817_cache")
DEFAULT_OUTPUT_DIR = Path("artifacts/phase3_sec_discovery_sector33_20260817_agent_reviewed")
DEFAULT_REVIEW_FILE = Path("config/phase3_sec_discovery_sector33_20260817_review_decisions.csv")
DEFAULT_BUNDLE_DIR = Path("reproducibility/phase3_sec_discovery_sector33_20260817")
DEFAULT_BUNDLE_NAME = "phase3_sec_discovery_sector33_20260817_sec_cache.tar.gz"
DEFAULT_MANIFEST_NAME = "phase3_sec_discovery_sector33_20260817_sec_cache_manifest.json"

EXPECTED_RESULT_COUNTS = {
    "issuers_attempted": 33,
    "filings_selected": 197,
    "retained_candidates": 11,
    "accepted": 0,
    "rejected": 7,
    "unresolved": 3,
    "future_scheduled": 1,
    "raw_candidates": 791,
}


class BundleError(RuntimeError):
    """Raised when the portability bundle is incomplete or invalid."""


@dataclass(frozen=True, slots=True)
class BundlePaths:
    repo_root: Path
    cache_dir: Path
    config_path: Path
    review_file: Path
    output_dir: Path
    bundle_dir: Path
    bundle_path: Path
    manifest_path: Path


def default_bundle_paths(repo_root: Path | None = None) -> BundlePaths:
    root = (repo_root or _repo_root()).resolve()
    bundle_dir = root / DEFAULT_BUNDLE_DIR
    return BundlePaths(
        repo_root=root,
        cache_dir=root / DEFAULT_CACHE_DIR,
        config_path=root / DEFAULT_CONFIG_PATH,
        review_file=root / DEFAULT_REVIEW_FILE,
        output_dir=root / DEFAULT_OUTPUT_DIR,
        bundle_dir=bundle_dir,
        bundle_path=bundle_dir / DEFAULT_BUNDLE_NAME,
        manifest_path=bundle_dir / DEFAULT_MANIFEST_NAME,
    )


def build_portable_bundle(
    *,
    repo_root: Path | None = None,
    cache_dir: Path | None = None,
    bundle_path: Path | None = None,
    manifest_path: Path | None = None,
    config_path: Path | None = None,
    review_file: Path | None = None,
) -> dict[str, Any]:
    paths = default_bundle_paths(repo_root=repo_root)
    cache_root = (cache_dir or paths.cache_dir).resolve()
    bundle_target = (bundle_path or paths.bundle_path).resolve()
    manifest_target = (manifest_path or paths.manifest_path).resolve()
    config_target = (config_path or paths.config_path).resolve()
    review_target = (review_file or paths.review_file).resolve()

    if not cache_root.exists():
        raise BundleError(f"Cache directory does not exist: {cache_root}")
    if not config_target.exists():
        raise BundleError(f"Final cache-only config is missing: {config_target}")
    if not review_target.exists():
        raise BundleError(f"Review decisions file is missing: {review_target}")

    bundle_target.parent.mkdir(parents=True, exist_ok=True)
    manifest_target.parent.mkdir(parents=True, exist_ok=True)

    manifest = _build_manifest(
        repo_root=paths.repo_root,
        cache_dir=cache_root,
        config_path=config_target,
        review_file=review_target,
        bundle_relative_path=_relative_to_repo(bundle_target, paths.repo_root),
    )
    _write_deterministic_tar_gz(
        repo_root=paths.repo_root,
        cache_dir=cache_root,
        bundle_path=bundle_target,
    )
    manifest["bundle_sha256"] = sha256_file(bundle_target)
    manifest["bundle_size_bytes"] = bundle_target.stat().st_size
    manifest_target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def restore_portable_bundle(
    *,
    repo_root: Path | None = None,
    bundle_path: Path | None = None,
    manifest_path: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    paths = default_bundle_paths(repo_root=repo_root)
    bundle_source = (bundle_path or paths.bundle_path).resolve()
    manifest_source = (manifest_path or paths.manifest_path).resolve()

    if not bundle_source.exists():
        raise BundleError(f"Bundle archive does not exist: {bundle_source}")
    if not manifest_source.exists():
        raise BundleError(f"Bundle manifest does not exist: {manifest_source}")

    manifest = json.loads(manifest_source.read_text(encoding="utf-8"))
    expected_cache_relative = PurePosixPath(str(manifest["authoritative_inputs"]["cache_dir"]).replace("\\", "/"))
    expected_cache_dir = paths.repo_root / Path(*expected_cache_relative.parts)
    backup_path: Path | None = None

    if expected_cache_dir.exists():
        if overwrite:
            _safe_rmtree(expected_cache_dir, paths.repo_root)
        else:
            backup_path = _reserve_backup_path(expected_cache_dir)
            shutil.move(str(expected_cache_dir), str(backup_path))

    with tempfile.TemporaryDirectory(prefix="phase3_cache_restore_", dir=paths.repo_root) as temp_dir_name:
        temp_root = Path(temp_dir_name)
        with tarfile.open(bundle_source, mode="r:gz") as archive:
            members = archive.getmembers()
            _validate_archive_members(members, expected_cache_relative)
            archive.extractall(path=temp_root)

        _verify_restored_tree(temp_root, manifest)

        staged_cache_dir = temp_root / Path(*expected_cache_relative.parts)
        if not staged_cache_dir.exists():
            raise BundleError(f"Archive did not contain the expected cache directory: {expected_cache_relative}")
        expected_cache_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged_cache_dir), str(expected_cache_dir))

    return {
        "restored_cache_dir": str(expected_cache_dir),
        "bundle_path": str(bundle_source),
        "manifest_path": str(manifest_source),
        "file_count": int(manifest["cache_summary"]["file_count"]),
        "cache_bytes": int(manifest["cache_summary"]["total_bytes"]),
        "preexisting_cache_backup_dir": str(backup_path) if backup_path is not None else None,
    }


def run_verified_reproduction(
    *,
    repo_root: Path | None = None,
    config_path: Path | None = None,
    cache_dir: Path | None = None,
    output_dir: Path | None = None,
    force: bool = True,
) -> dict[str, Any]:
    paths = default_bundle_paths(repo_root=repo_root)
    base_config = (config_path or paths.config_path).resolve()
    cache_override = cache_dir.resolve() if cache_dir is not None else None
    output_override = output_dir.resolve() if output_dir is not None else None

    if cache_override is None and output_override is None:
        effective_config = base_config
        effective_output_dir = paths.output_dir
    else:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yaml",
            delete=False,
            encoding="utf-8",
            dir=paths.repo_root,
        ) as handle:
            temp_config_path = Path(handle.name)
            _write_config_override(
                source_config=base_config,
                destination=temp_config_path,
                cache_dir=cache_override,
                output_dir=output_override,
            )
        effective_config = temp_config_path
        effective_output_dir = output_override or paths.output_dir

    import src.sec.edgar as sec_edgar

    original_builder = sec_edgar.build_sec_http_client

    def _build_guarded_client(config: sec_edgar.SECFilingSourceConfig) -> sec_edgar.SecHttpClient:
        return sec_edgar.SecHttpClient(
            user_agent=config.sec_user_agent or "cache-only-replay",
            request_delay_seconds=config.request_delay_seconds,
            max_retries=config.max_retries,
            timeout_seconds=config.timeout_seconds,
            opener=_raise_network_use,
        )

    sec_edgar.build_sec_http_client = _build_guarded_client
    try:
        run_phase2_batch(config_path=effective_config, force=force)
    finally:
        sec_edgar.build_sec_http_client = original_builder
        if effective_config != base_config and effective_config.exists():
            effective_config.unlink()

    summary = summarize_reproduction_output(effective_output_dir)
    validate_expected_counts(summary)
    return summary


def summarize_reproduction_output(output_dir: Path) -> dict[str, Any]:
    status_rows = _read_csv_rows(output_dir / "company_processing_status.csv")
    review_rows = _read_csv_rows(output_dir / "candidate_review_queue.csv")
    metrics_rows = _read_csv_rows(output_dir / "sec_acquisition_metrics.csv")

    if not status_rows:
        raise BundleError(f"Reproduction output is missing company status rows: {output_dir}")
    if not metrics_rows:
        raise BundleError(f"Reproduction output is missing SEC acquisition metrics: {output_dir}")

    status_counts = Counter(
        (row.get("processing_status", "") or "").strip()
        for row in status_rows
    )
    cache_misses = sum(int(row.get("cache_misses_total", "0") or 0) for row in metrics_rows)
    warnings = sum(int(row.get("warning_count", "0") or 0) for row in status_rows)
    processed = sum(int(row.get("filings_processed", "0") or 0) for row in status_rows)
    selected = sum(int(row.get("filings_selected", "0") or 0) for row in status_rows)

    summary = {
        "output_dir": str(output_dir),
        "issuers_attempted": len(status_rows),
        "filings_selected": selected,
        "filings_processed": processed,
        "retained_candidates": len(review_rows),
        "accepted": sum(int(row.get("accepted_events", "0") or 0) for row in status_rows),
        "rejected": sum(int(row.get("rejected_events", "0") or 0) for row in status_rows),
        "unresolved": sum(int(row.get("unresolved_events", "0") or 0) for row in status_rows),
        "future_scheduled": sum(int(row.get("future_scheduled_events", "0") or 0) for row in status_rows),
        "raw_candidates": sum(int(row.get("raw_candidate_count", "0") or 0) for row in status_rows),
        "warning_count": warnings,
        "cache_misses_total": cache_misses,
        "failed_status_rows": int(status_counts.get("failed", 0)),
        "status_counts": dict(sorted(status_counts.items())),
    }

    if processed != selected:
        raise BundleError(
            f"Selected filing count ({selected}) did not match processed filing count ({processed})."
        )
    if warnings != 0:
        raise BundleError(f"Expected zero warnings, found {warnings}.")
    if cache_misses != 0:
        raise BundleError(
            f"Expected zero SEC cache misses during cache-only replay, found {cache_misses}."
        )
    if summary["failed_status_rows"] != 0:
        raise BundleError("Cache-only replay reported failed issuer rows.")
    return summary


def validate_expected_counts(summary: dict[str, Any]) -> None:
    for key, expected in EXPECTED_RESULT_COUNTS.items():
        observed = int(summary.get(key, -1))
        if observed != expected:
            raise BundleError(f"Expected {key}={expected}, observed {observed}.")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_manifest(
    *,
    repo_root: Path,
    cache_dir: Path,
    config_path: Path,
    review_file: Path,
    bundle_relative_path: str,
) -> dict[str, Any]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    expected_tickers = list(config.get("ticker_subset") or [])
    if not expected_tickers:
        raise BundleError(f"Final cache-only config did not include ticker_subset: {config_path}")

    category_counts: Counter[str] = Counter()
    category_bytes: defaultdict[str, int] = defaultdict(int)
    file_inventory: list[dict[str, Any]] = []
    selected_filings: list[dict[str, Any]] = []

    total_bytes = 0
    for path in _iter_files(cache_dir):
        relative_cache_path = path.relative_to(cache_dir)
        relative_repo_path = _relative_to_repo(path, repo_root)
        category = _categorize_cache_file(relative_cache_path)
        digest = sha256_file(path)
        size = path.stat().st_size
        total_bytes += size
        category_counts[category] += 1
        category_bytes[category] += size
        file_inventory.append(
            {
                "path": relative_repo_path,
                "category": category,
                "size_bytes": size,
                "sha256": digest,
            }
        )
        if relative_cache_path.name == "metadata.json":
            metadata = json.loads(path.read_text(encoding="utf-8"))
            selected_filings.append(
                {
                    "ticker": str(metadata["ticker"]),
                    "cik": str(metadata["cik"]),
                    "accession_number": str(metadata["accession_number"]),
                    "filing_type": str(metadata["form"]),
                    "filing_date": str(metadata["filing_date"]),
                    "primary_document": str(metadata["primary_document"]),
                    "submission_source_file": str(metadata["submission_source_file"]),
                    "document_url": str(metadata["document_url"]),
                    "index_url": str(metadata["index_url"]),
                }
            )

    selected_filings = sorted(
        selected_filings,
        key=lambda row: (row["ticker"], row["filing_date"], row["accession_number"]),
    )
    selected_tickers = sorted({row["ticker"] for row in selected_filings})
    if selected_tickers != sorted(expected_tickers):
        raise BundleError(
            "Selected ticker set derived from metadata.json files did not match the final cache-only config."
        )
    if len(selected_filings) != EXPECTED_RESULT_COUNTS["filings_selected"]:
        raise BundleError(
            f"Expected {EXPECTED_RESULT_COUNTS['filings_selected']} filing metadata files, found {len(selected_filings)}."
        )

    return {
        "bundle_description": "Portable SEC evidence bundle for the final reviewed 33-issuer discovery closeout.",
        "bundle_file": bundle_relative_path,
        "bundle_sha256": "",
        "bundle_size_bytes": 0,
        "authoritative_inputs": {
            "cache_dir": _relative_to_repo(cache_dir, repo_root),
            "final_cache_only_config": _relative_to_repo(config_path, repo_root),
            "review_decisions_file": _relative_to_repo(review_file, repo_root),
            "universe_file": str(config["universe_file"]),
            "price_data_path": str(config["price_data_path"]),
            "output_dir_on_replay": str(config["output_dir"]),
        },
        "expected_result": EXPECTED_RESULT_COUNTS,
        "cache_summary": {
            "file_count": len(file_inventory),
            "total_bytes": total_bytes,
            "category_counts": dict(sorted(category_counts.items())),
            "category_bytes": dict(sorted(category_bytes.items())),
            "selected_ticker_count": len(selected_tickers),
            "selected_filing_count": len(selected_filings),
            "selected_tickers": selected_tickers,
            "selected_filings": selected_filings,
        },
        "file_inventory": file_inventory,
    }


def _write_deterministic_tar_gz(*, repo_root: Path, cache_dir: Path, bundle_path: Path) -> None:
    with tempfile.NamedTemporaryFile(prefix="phase3_cache_bundle_", suffix=".tar", delete=False, dir=repo_root) as temp_tar:
        temp_tar_path = Path(temp_tar.name)
    try:
        with tarfile.open(temp_tar_path, mode="w") as archive:
            for path in _iter_files(cache_dir):
                arcname = PurePosixPath(_relative_to_repo(cache_dir, repo_root)) / PurePosixPath(path.relative_to(cache_dir).as_posix())
                archive.add(path, arcname=str(arcname), filter=_tarinfo_filter)

        with temp_tar_path.open("rb") as source_handle, bundle_path.open("wb") as bundle_handle:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=bundle_handle,
                compresslevel=6,
                mtime=0,
            ) as gz_handle:
                shutil.copyfileobj(source_handle, gz_handle)
    finally:
        if temp_tar_path.exists():
            temp_tar_path.unlink()


def _tarinfo_filter(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = 0
    info.mode = 0o755 if info.isdir() else 0o644
    return info


def _validate_archive_members(members: list[tarfile.TarInfo], expected_cache_relative: PurePosixPath) -> None:
    expected_prefix = expected_cache_relative.as_posix().rstrip("/") + "/"
    for member in members:
        member_path = PurePosixPath(member.name)
        if member_path.is_absolute():
            raise BundleError(f"Archive member used an absolute path: {member.name}")
        if ".." in member_path.parts:
            raise BundleError(f"Archive member attempted path traversal: {member.name}")
        if not member.name.startswith(expected_prefix):
            raise BundleError(
                f"Archive member fell outside the expected cache directory {expected_cache_relative}: {member.name}"
            )


def _verify_restored_tree(temp_root: Path, manifest: dict[str, Any]) -> None:
    manifest_files = manifest.get("file_inventory") or []
    actual_paths: set[str] = set()
    for record in manifest_files:
        relative_path = str(record["path"]).replace("\\", "/")
        extracted_path = temp_root / Path(*PurePosixPath(relative_path).parts)
        actual_paths.add(relative_path)
        if not extracted_path.exists():
            raise BundleError(f"Restored bundle was missing expected file: {relative_path}")
        size = extracted_path.stat().st_size
        if size != int(record["size_bytes"]):
            raise BundleError(
                f"Restored file size mismatch for {relative_path}: expected {record['size_bytes']}, found {size}."
            )
        digest = sha256_file(extracted_path)
        if digest != str(record["sha256"]):
            raise BundleError(f"Restored file hash mismatch for {relative_path}.")

    extracted_paths = {
        _relative_to_repo(path, temp_root)
        for path in _iter_files(temp_root)
    }
    extras = sorted(extracted_paths - actual_paths)
    if extras:
        raise BundleError(f"Restored bundle contained unexpected files: {extras[:5]}")


def _write_config_override(
    *,
    source_config: Path,
    destination: Path,
    cache_dir: Path | None,
    output_dir: Path | None,
) -> None:
    raw = yaml.safe_load(source_config.read_text(encoding="utf-8"))
    if cache_dir is not None:
        raw["cache_dir"] = cache_dir.as_posix()
    if output_dir is not None:
        raw["output_dir"] = output_dir.as_posix()
    destination.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def _raise_network_use(*_: Any, **__: Any) -> Any:
    raise AssertionError("Network should not be used during final cache-only replay.")


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _safe_rmtree(target: Path, repo_root: Path) -> None:
    resolved_target = target.resolve()
    resolved_root = repo_root.resolve()
    if resolved_root not in resolved_target.parents:
        raise BundleError(f"Refusing to delete path outside repo root: {resolved_target}")
    shutil.rmtree(resolved_target)


def _reserve_backup_path(target: Path) -> Path:
    base = target.parent / f"{target.name}_pre_restore_backup"
    candidate = base
    counter = 1
    while candidate.exists():
        candidate = target.parent / f"{target.name}_pre_restore_backup_{counter}"
        counter += 1
    return candidate


def _iter_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def _categorize_cache_file(relative_cache_path: Path) -> str:
    posix = PurePosixPath(relative_cache_path.as_posix())
    parts = posix.parts
    if len(parts) >= 2 and parts[0] == "submissions":
        if "-submissions-" in posix.name:
            return "historical_submissions_json"
        return "submissions_json"
    if len(parts) >= 4 and parts[0] == "filings" and posix.name == "index.json":
        return "filing_index_json"
    if len(parts) >= 4 and parts[0] == "filings" and posix.name == "metadata.json":
        return "filing_metadata_json"
    if len(parts) >= 4 and parts[0] == "filings":
        return "filing_primary_document"
    raise BundleError(f"Encountered unexpected cache file layout: {relative_cache_path}")


def _relative_to_repo(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]
