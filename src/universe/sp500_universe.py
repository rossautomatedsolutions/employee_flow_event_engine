from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = {
    "ticker",
    "company_name",
    "cik",
    "gics_sector",
    "gics_sub_industry",
    "issuer_id",
    "primary_ticker",
    "is_primary_share_class",
}


@dataclass(slots=True)
class DuplicateCIKGroup:
    cik: str
    tickers: tuple[str, ...]
    issuer_id: str
    primary_ticker: str
    is_legitimate_share_class_group: bool


@dataclass(slots=True)
class UniverseValidationReport:
    source_path: str
    row_count: int
    unique_tickers: int
    unique_ciks: int
    duplicate_tickers: list[str]
    duplicate_cik_groups: list[DuplicateCIKGroup]
    legitimate_share_class_groups: list[DuplicateCIKGroup]
    warnings: list[str]
    errors: list[str]


@dataclass(slots=True)
class LoadedSP500Universe:
    companies: pd.DataFrame
    report: UniverseValidationReport


def _normalize_column_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _normalize_text(value: object) -> str:
    text = str(value).strip()
    return re.sub(r"\s+", " ", text)


def _normalize_ticker(value: object) -> str:
    ticker = _normalize_text(value).upper().replace("/", ".").replace("-", ".")
    ticker = ticker.replace(" ", "")
    if not ticker:
        raise ValueError("Universe rows require a non-empty ticker")
    if not re.fullmatch(r"[A-Z0-9.]+", ticker):
        raise ValueError(f"Unsupported ticker format {value!r}; use letters, digits, and '.' only")
    return ticker


def _normalize_cik(value: object) -> str:
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        raise ValueError(f"Universe rows require a numeric CIK; got {value!r}")
    return digits.zfill(10)


def _normalize_bool(value: object) -> bool:
    normalized = _normalize_text(value).lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    if normalized == "":
        raise ValueError("Blank is_primary_share_class values are not allowed")
    raise ValueError(f"Unsupported boolean value {value!r} for is_primary_share_class")


def _normalize_universe_frame(frame: pd.DataFrame) -> pd.DataFrame:
    renamed = frame.rename(columns=_normalize_column_name).copy()
    missing = sorted(REQUIRED_COLUMNS.difference(renamed.columns))
    if missing:
        raise ValueError(f"Universe file missing required columns: {missing}")

    normalized = renamed.loc[:, sorted(set(renamed.columns))].copy()
    normalized["ticker"] = normalized["ticker"].map(_normalize_ticker)
    normalized["company_name"] = normalized["company_name"].map(_normalize_text)
    normalized["cik"] = normalized["cik"].map(_normalize_cik)
    normalized["gics_sector"] = normalized["gics_sector"].map(_normalize_text)
    normalized["gics_sub_industry"] = normalized["gics_sub_industry"].map(_normalize_text)
    normalized["issuer_id"] = normalized["issuer_id"].map(_normalize_text)
    normalized.loc[normalized["issuer_id"] == "", "issuer_id"] = normalized.loc[normalized["issuer_id"] == "", "cik"]
    normalized["primary_ticker"] = normalized["primary_ticker"].map(_normalize_ticker)
    normalized["is_primary_share_class"] = normalized["is_primary_share_class"].map(_normalize_bool)

    if "issuer_name" in normalized.columns:
        normalized["issuer_name"] = normalized["issuer_name"].map(_normalize_text)
    else:
        normalized["issuer_name"] = normalized["company_name"]
    return normalized


def _build_validation_report(frame: pd.DataFrame, source_path: Path) -> UniverseValidationReport:
    errors: list[str] = []
    warnings: list[str] = []

    duplicate_tickers = sorted(frame.loc[frame.duplicated("ticker", keep=False), "ticker"].unique().tolist())
    if duplicate_tickers:
        errors.append(
            "Duplicate tickers remain after normalization: "
            + ", ".join(duplicate_tickers)
            + ". Check share-class naming and ticker aliases."
        )

    duplicate_cik_groups: list[DuplicateCIKGroup] = []
    legitimate_share_class_groups: list[DuplicateCIKGroup] = []
    for cik, group in frame.groupby("cik", sort=True):
        if len(group) == 1:
            row = group.iloc[0]
            if row["primary_ticker"] != row["ticker"]:
                errors.append(
                    f"Unique issuer CIK {cik} has primary_ticker={row['primary_ticker']} but only ticker {row['ticker']} exists."
                )
            if not bool(row["is_primary_share_class"]):
                errors.append(f"Unique issuer CIK {cik} must mark its lone row as is_primary_share_class=true.")
            continue

        tickers = tuple(sorted(group["ticker"].tolist()))
        primary_tickers = sorted(group["primary_ticker"].unique().tolist())
        issuer_ids = sorted(group["issuer_id"].unique().tolist())
        primary_rows = group[group["is_primary_share_class"]]
        is_legitimate = (
            len(primary_tickers) == 1
            and len(issuer_ids) == 1
            and len(primary_rows) == 1
            and primary_tickers[0] in tickers
            and primary_rows.iloc[0]["ticker"] == primary_tickers[0]
        )
        group_report = DuplicateCIKGroup(
            cik=str(cik),
            tickers=tickers,
            issuer_id=issuer_ids[0] if issuer_ids else "",
            primary_ticker=primary_tickers[0] if primary_tickers else "",
            is_legitimate_share_class_group=is_legitimate,
        )
        duplicate_cik_groups.append(group_report)
        if is_legitimate:
            legitimate_share_class_groups.append(group_report)
            continue

        errors.append(
            "Duplicate CIK group "
            f"{cik} is malformed. Tickers={list(tickers)}, issuer_ids={issuer_ids}, primary_tickers={primary_tickers}, "
            f"primary_rows={primary_rows['ticker'].tolist()}. Legitimate share-class groups must share one issuer_id and "
            "declare exactly one primary share class."
        )

    duplicate_cik_count = len(duplicate_cik_groups)
    if duplicate_cik_count and duplicate_cik_count == len(legitimate_share_class_groups):
        warnings.append(
            f"Universe contains {duplicate_cik_count} legitimate multi-share-class issuer group(s); filings should be processed once per issuer."
        )

    return UniverseValidationReport(
        source_path=str(source_path),
        row_count=int(len(frame)),
        unique_tickers=int(frame["ticker"].nunique()),
        unique_ciks=int(frame["cik"].nunique()),
        duplicate_tickers=duplicate_tickers,
        duplicate_cik_groups=duplicate_cik_groups,
        legitimate_share_class_groups=legitimate_share_class_groups,
        warnings=warnings,
        errors=errors,
    )


def load_sp500_universe(path: Path) -> LoadedSP500Universe:
    if not path.exists():
        raise ValueError(f"Universe file not found: {path}")
    try:
        raw = pd.read_csv(path, dtype=str).fillna("")
    except Exception as exc:  # pragma: no cover - exercised through calling code
        raise ValueError(f"Unable to read universe file {path}: {exc}") from exc

    try:
        normalized = _normalize_universe_frame(raw)
    except ValueError as exc:
        raise ValueError(f"Universe validation failed for {path}: {exc}") from exc

    report = _build_validation_report(normalized, path)
    if report.errors:
        joined = "\n".join(f"- {message}" for message in report.errors)
        raise ValueError(f"Universe validation failed for {path}:\n{joined}")

    ordered_columns = [
        "ticker",
        "company_name",
        "issuer_name",
        "issuer_id",
        "cik",
        "gics_sector",
        "gics_sub_industry",
        "primary_ticker",
        "is_primary_share_class",
    ]
    normalized = normalized.reindex(columns=ordered_columns).sort_values(
        ["primary_ticker", "ticker"],
        ignore_index=True,
    )
    return LoadedSP500Universe(companies=normalized, report=report)


def render_universe_validation_report_markdown(report: UniverseValidationReport) -> str:
    lines = [
        "# Universe Validation Report",
        "",
        f"- Source file: {report.source_path}",
        f"- Universe rows: {report.row_count}",
        f"- Unique tickers: {report.unique_tickers}",
        f"- Unique issuers / CIKs: {report.unique_ciks}",
        f"- Duplicate tickers: {len(report.duplicate_tickers)}",
        f"- Duplicate CIK groups: {len(report.duplicate_cik_groups)}",
        f"- Legitimate share-class groups: {len(report.legitimate_share_class_groups)}",
        "",
        "## Duplicate Tickers",
        "",
    ]
    if report.duplicate_tickers:
        lines.extend(f"- {ticker}" for ticker in report.duplicate_tickers)
    else:
        lines.append("- none")

    lines.extend(["", "## Duplicate CIK Groups", ""])
    if report.duplicate_cik_groups:
        for group in report.duplicate_cik_groups:
            legit = "yes" if group.is_legitimate_share_class_group else "no"
            lines.append(
                f"- CIK {group.cik}: tickers={list(group.tickers)}, primary_ticker={group.primary_ticker}, "
                f"issuer_id={group.issuer_id}, legitimate_share_class_group={legit}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Warnings", ""])
    if report.warnings:
        lines.extend(f"- {warning}" for warning in report.warnings)
    else:
        lines.append("- none")

    lines.extend(["", "## Errors", ""])
    if report.errors:
        lines.extend(f"- {error}" for error in report.errors)
    else:
        lines.append("- none")

    return "\n".join(lines) + "\n"


def select_universe_companies(
    universe: pd.DataFrame,
    ticker_subset: list[str] | None = None,
    sector_subset: list[str] | None = None,
    max_companies: int | None = None,
) -> pd.DataFrame:
    selected = universe.copy()
    if ticker_subset:
        normalized_tickers = {_normalize_ticker(ticker) for ticker in ticker_subset}
        selected = selected[selected["ticker"].isin(normalized_tickers)].copy()

    if sector_subset:
        normalized_sectors = {_normalize_text(sector).casefold() for sector in sector_subset}
        selected = selected[selected["gics_sector"].map(lambda value: _normalize_text(value).casefold()).isin(normalized_sectors)].copy()

    selected = selected.sort_values(["primary_ticker", "ticker"], ignore_index=True)
    if max_companies is not None:
        if max_companies <= 0:
            raise ValueError("max_companies must be positive when provided")
        selected = selected.head(max_companies).copy()
    return selected.reset_index(drop=True)
