from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date
from html import unescape
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

from src.data.sec_parser import ESPPFilingHint, FilingDocument, extract_espp_hints, load_filing_documents_from_fixtures

LOGGER = logging.getLogger(__name__)

DATA_SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"
DEFAULT_SEC_FORMS: tuple[str, ...] = ("10-K", "10-K/A", "DEF 14A")
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


@dataclass(slots=True)
class SECFilingSourceConfig:
    source: str = "fixture"
    fixture_dir: Path | None = None
    sec_user_agent: str | None = None
    forms: tuple[str, ...] = DEFAULT_SEC_FORMS
    filing_start_date: date | None = None
    filing_end_date: date | None = None
    max_filings_per_issuer: int = 6
    cache_only: bool = False
    request_delay_seconds: float = 0.2
    max_retries: int = 3
    timeout_seconds: float = 30.0


@dataclass(slots=True)
class SecFilingMetadata:
    ticker: str
    cik: str
    company_name: str
    accession_number: str
    accession_nodashes: str
    form: str
    filing_date: date
    report_date: date | None
    primary_document: str
    primary_doc_description: str
    submission_source_file: str

    @property
    def cik_archive_component(self) -> str:
        return str(int(self.cik))

    @property
    def filing_directory_url(self) -> str:
        return f"{SEC_ARCHIVES_URL}/{self.cik_archive_component}/{self.accession_nodashes}"

    @property
    def index_url(self) -> str:
        return f"{self.filing_directory_url}/index.json"

    @property
    def document_url(self) -> str:
        return f"{self.filing_directory_url}/{self.primary_document}"


@dataclass(slots=True)
class FilingAcquisitionMetrics:
    ticker: str
    cik: str
    source_mode: str
    cache_only: bool
    filings_discovered: int = 0
    filings_matching_forms: int = 0
    filings_in_date_window: int = 0
    filings_selected: int = 0
    filings_processed: int = 0
    configured_filing_start_date: date | None = None
    configured_filing_end_date: date | None = None
    effective_filing_start_date: date | None = None
    effective_filing_end_date: date | None = None
    submissions_cache_hits: int = 0
    submissions_cache_misses: int = 0
    index_cache_hits: int = 0
    index_cache_misses: int = 0
    document_cache_hits: int = 0
    document_cache_misses: int = 0
    retry_count: int = 0
    warning_messages: list[str] = field(default_factory=list)

    @property
    def warning_count(self) -> int:
        return len(self.warning_messages)

    @property
    def cache_hits_total(self) -> int:
        return self.submissions_cache_hits + self.index_cache_hits + self.document_cache_hits

    @property
    def cache_misses_total(self) -> int:
        return self.submissions_cache_misses + self.index_cache_misses + self.document_cache_misses

    def to_row(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "cik": self.cik,
            "source_mode": self.source_mode,
            "cache_only": self.cache_only,
            "filings_discovered": int(self.filings_discovered),
            "filings_matching_forms": int(self.filings_matching_forms),
            "filings_in_date_window": int(self.filings_in_date_window),
            "filings_selected": int(self.filings_selected),
            "filings_processed": int(self.filings_processed),
            "configured_filing_start_date": self.configured_filing_start_date.isoformat() if self.configured_filing_start_date else None,
            "configured_filing_end_date": self.configured_filing_end_date.isoformat() if self.configured_filing_end_date else None,
            "effective_filing_start_date": self.effective_filing_start_date.isoformat() if self.effective_filing_start_date else None,
            "effective_filing_end_date": self.effective_filing_end_date.isoformat() if self.effective_filing_end_date else None,
            "submissions_cache_hits": int(self.submissions_cache_hits),
            "submissions_cache_misses": int(self.submissions_cache_misses),
            "index_cache_hits": int(self.index_cache_hits),
            "index_cache_misses": int(self.index_cache_misses),
            "document_cache_hits": int(self.document_cache_hits),
            "document_cache_misses": int(self.document_cache_misses),
            "cache_hits_total": int(self.cache_hits_total),
            "cache_misses_total": int(self.cache_misses_total),
            "retry_count": int(self.retry_count),
            "warning_count": int(self.warning_count),
            "warnings": " | ".join(self.warning_messages),
        }


@dataclass(slots=True)
class Phase2FilingAcquisitionResult:
    documents: list[FilingDocument]
    hints: list[ESPPFilingHint]
    inventory_frame: pd.DataFrame
    screening_frame: pd.DataFrame
    metrics: FilingAcquisitionMetrics


class SecHttpClient:
    def __init__(
        self,
        user_agent: str,
        request_delay_seconds: float,
        max_retries: int,
        timeout_seconds: float,
        opener: Callable[..., object] = urlopen,
        sleep_func: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.user_agent = user_agent
        self.request_delay_seconds = request_delay_seconds
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self._opener = opener
        self._sleep = sleep_func
        self._clock = clock
        self._last_request_at: float | None = None

    def get_json(self, url: str, metrics: FilingAcquisitionMetrics | None = None) -> dict[str, object]:
        payload = self.get_text(url, metrics=metrics)
        return json.loads(payload)

    def get_text(self, url: str, metrics: FilingAcquisitionMetrics | None = None) -> str:
        attempt = 0
        while True:
            self._respect_rate_limit()
            request = Request(url, headers={"User-Agent": self.user_agent})
            try:
                with self._opener(request, timeout=self.timeout_seconds) as response:
                    body = response.read()
                self._last_request_at = self._clock()
                return body.decode("utf-8", errors="replace")
            except HTTPError as exc:
                self._last_request_at = self._clock()
                if exc.code in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                    if metrics is not None:
                        metrics.retry_count += 1
                    self._sleep(self.request_delay_seconds * (2**attempt))
                    attempt += 1
                    continue
                raise
            except URLError:
                self._last_request_at = self._clock()
                if attempt < self.max_retries:
                    if metrics is not None:
                        metrics.retry_count += 1
                    self._sleep(self.request_delay_seconds * (2**attempt))
                    attempt += 1
                    continue
                raise

    def _respect_rate_limit(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = self._clock() - self._last_request_at
        remaining = self.request_delay_seconds - elapsed
        if remaining > 0:
            self._sleep(remaining)


def build_sec_http_client(config: SECFilingSourceConfig) -> SecHttpClient:
    if not config.sec_user_agent and not config.cache_only:
        raise ValueError("SEC acquisition requires a non-empty user-agent string")
    user_agent = config.sec_user_agent or "cache-only-replay"
    return SecHttpClient(
        user_agent=user_agent,
        request_delay_seconds=config.request_delay_seconds,
        max_retries=config.max_retries,
        timeout_seconds=config.timeout_seconds,
    )


def _matches_form_filter(form: str, filing_config: SECFilingSourceConfig) -> bool:
    forms = {candidate.strip().upper() for candidate in filing_config.forms if candidate and candidate.strip()}
    return form.strip().upper() in forms


def _in_filing_date_window(filing_date: date, filing_config: SECFilingSourceConfig) -> bool:
    if filing_config.filing_start_date is not None and filing_date < filing_config.filing_start_date:
        return False
    if filing_config.filing_end_date is not None and filing_date > filing_config.filing_end_date:
        return False
    return True


def _effective_date_range(dates: list[date]) -> tuple[date | None, date | None]:
    if not dates:
        return None, None
    return min(dates), max(dates)


def load_batch_filing_inputs(
    filing_config: SECFilingSourceConfig,
    cache_dir: Path,
    ticker: str,
    cik: str,
    company_name: str,
) -> Phase2FilingAcquisitionResult:
    if filing_config.source == "fixture":
        return _load_fixture_inputs(filing_config, ticker=ticker, cik=cik)
    if filing_config.source == "sec":
        client = build_sec_http_client(filing_config)
        return _load_sec_inputs(
            filing_config,
            cache_dir=cache_dir,
            client=client,
            ticker=ticker,
            cik=cik,
            company_name=company_name,
        )
    raise ValueError(f"Unsupported filings.source: {filing_config.source!r}")


def _load_fixture_inputs(
    filing_config: SECFilingSourceConfig,
    ticker: str,
    cik: str,
) -> Phase2FilingAcquisitionResult:
    fixture_dir = filing_config.fixture_dir
    discovered_documents = load_filing_documents_from_fixtures(fixture_dir, ticker=ticker) if fixture_dir is not None else []
    form_matched_documents = [document for document in discovered_documents if _matches_form_filter(document.filing_type, filing_config)]
    in_window_documents = [document for document in form_matched_documents if _in_filing_date_window(document.filing_date, filing_config)]
    selected_documents = in_window_documents[: filing_config.max_filings_per_issuer]
    effective_start_date, effective_end_date = _effective_date_range([document.filing_date for document in selected_documents])
    hints = [extract_espp_hints(document) for document in selected_documents]
    metrics = FilingAcquisitionMetrics(
        ticker=ticker,
        cik=cik,
        source_mode="fixture",
        cache_only=bool(filing_config.cache_only),
        filings_discovered=len(discovered_documents),
        filings_matching_forms=len(form_matched_documents),
        filings_in_date_window=len(in_window_documents),
        filings_selected=len(selected_documents),
        filings_processed=len(selected_documents),
        configured_filing_start_date=filing_config.filing_start_date,
        configured_filing_end_date=filing_config.filing_end_date,
        effective_filing_start_date=effective_start_date,
        effective_filing_end_date=effective_end_date,
    )

    selected_source_ids = {document.source_id for document in selected_documents}
    screened_source_ids = {
        hint.source_id
        for hint in hints
        if bool(hint.matched_terms or hint.confidence > 0)
    }
    inventory_rows = [
        {
            "ticker": document.ticker,
            "cik": cik,
            "source_mode": "fixture",
            "source_id": document.source_id,
            "accession_number": document.accession_number or document.source_id,
            "filing_type": document.filing_type,
            "filing_date": document.filing_date.isoformat(),
            "report_date": document.report_date.isoformat() if document.report_date else None,
            "primary_document": None,
            "primary_doc_description": None,
            "filing_url": document.source_url,
            "index_url": None,
            "document_cache_path": document.source_cache_path,
            "configured_filing_start_date": filing_config.filing_start_date.isoformat() if filing_config.filing_start_date else None,
            "configured_filing_end_date": filing_config.filing_end_date.isoformat() if filing_config.filing_end_date else None,
            "effective_filing_start_date": effective_start_date.isoformat() if effective_start_date else None,
            "effective_filing_end_date": effective_end_date.isoformat() if effective_end_date else None,
            "matches_form_filter": _matches_form_filter(document.filing_type, filing_config),
            "in_filing_date_window": _in_filing_date_window(document.filing_date, filing_config),
            "selected_after_safety_cap": document.source_id in selected_source_ids,
            "screening_passed": document.source_id in screened_source_ids,
            "submissions_source": "na",
            "index_source": "na",
            "document_source": "fixture" if document.source_id in selected_source_ids else "not_selected",
            "processed_successfully": document.source_id in selected_source_ids,
            "warning": "",
        }
        for document in discovered_documents
    ]
    screening_rows = _screening_rows(selected_documents, hints, cik=cik)
    return Phase2FilingAcquisitionResult(
        documents=selected_documents,
        hints=hints,
        inventory_frame=pd.DataFrame(inventory_rows),
        screening_frame=pd.DataFrame(screening_rows),
        metrics=metrics,
    )


def _load_sec_inputs(
    filing_config: SECFilingSourceConfig,
    cache_dir: Path,
    client: SecHttpClient,
    ticker: str,
    cik: str,
    company_name: str,
) -> Phase2FilingAcquisitionResult:
    metrics = FilingAcquisitionMetrics(
        ticker=ticker,
        cik=cik,
        source_mode="sec",
        cache_only=bool(filing_config.cache_only),
        configured_filing_start_date=filing_config.filing_start_date,
        configured_filing_end_date=filing_config.filing_end_date,
    )
    cache_root = cache_dir
    cache_root.mkdir(parents=True, exist_ok=True)

    submissions_payload, _ = _read_or_fetch_json(
        client=client,
        cache_path=_submissions_cache_path(cache_root, cik),
        url=f"{DATA_SEC_SUBMISSIONS_URL}/CIK{cik}.json",
        cache_only=filing_config.cache_only,
        metrics=metrics,
        hit_field="submissions_cache_hits",
        miss_field="submissions_cache_misses",
        label=f"submissions JSON for {ticker}",
    )
    discovered_metadata = _select_filing_metadata(
        submissions_payload,
        filing_config=filing_config,
        client=client,
        cache_root=cache_root,
        ticker=ticker,
        cik=cik,
        company_name=company_name,
        metrics=metrics,
    )
    metrics.filings_discovered = len(discovered_metadata)
    form_matched_metadata = [metadata for metadata in discovered_metadata if _matches_form_filter(metadata.form, filing_config)]
    in_window_metadata = [metadata for metadata in form_matched_metadata if _in_filing_date_window(metadata.filing_date, filing_config)]
    selected_filings = in_window_metadata[: filing_config.max_filings_per_issuer]
    metrics.filings_matching_forms = len(form_matched_metadata)
    metrics.filings_in_date_window = len(in_window_metadata)
    metrics.filings_selected = len(selected_filings)
    effective_start_date, effective_end_date = _effective_date_range([metadata.filing_date for metadata in selected_filings])
    metrics.effective_filing_start_date = effective_start_date
    metrics.effective_filing_end_date = effective_end_date

    documents: list[FilingDocument] = []
    hints: list[ESPPFilingHint] = []
    selected_accessions = {metadata.accession_number for metadata in selected_filings}
    inventory_rows_by_accession = {
        metadata.accession_number: {
            "ticker": metadata.ticker,
            "cik": metadata.cik,
            "source_mode": "sec",
            "source_id": metadata.accession_number,
            "accession_number": metadata.accession_number,
            "filing_type": metadata.form,
            "filing_date": metadata.filing_date.isoformat(),
            "report_date": metadata.report_date.isoformat() if metadata.report_date else None,
            "primary_document": metadata.primary_document,
            "primary_doc_description": metadata.primary_doc_description,
            "filing_url": metadata.document_url,
            "index_url": metadata.index_url,
            "document_cache_path": str(_filing_directory(cache_root, cik, metadata.accession_nodashes) / metadata.primary_document),
            "configured_filing_start_date": filing_config.filing_start_date.isoformat() if filing_config.filing_start_date else None,
            "configured_filing_end_date": filing_config.filing_end_date.isoformat() if filing_config.filing_end_date else None,
            "effective_filing_start_date": effective_start_date.isoformat() if effective_start_date else None,
            "effective_filing_end_date": effective_end_date.isoformat() if effective_end_date else None,
            "matches_form_filter": _matches_form_filter(metadata.form, filing_config),
            "in_filing_date_window": _in_filing_date_window(metadata.filing_date, filing_config),
            "selected_after_safety_cap": metadata.accession_number in selected_accessions,
            "screening_passed": False,
            "submissions_source": metadata.submission_source_file,
            "index_source": "not_requested",
            "document_source": "not_requested",
            "processed_successfully": False,
            "warning": "",
        }
        for metadata in discovered_metadata
    }
    for metadata in selected_filings:
        try:
            document, hint, inventory_row = _download_sec_filing(
                filing_config=filing_config,
                cache_root=cache_root,
                client=client,
                metadata=metadata,
                metrics=metrics,
            )
            documents.append(document)
            hints.append(hint)
            inventory_rows_by_accession[metadata.accession_number] = inventory_row
        except Exception as exc:
            message = f"{ticker} {metadata.form} {metadata.accession_number}: {exc}"
            LOGGER.warning("%s", message)
            metrics.warning_messages.append(message)
            inventory_rows_by_accession[metadata.accession_number] = {
                **inventory_rows_by_accession[metadata.accession_number],
                "index_source": "error",
                "document_source": "error",
                "processed_successfully": False,
                "warning": str(exc),
            }

    metrics.filings_processed = len(documents)

    screening_rows = _screening_rows(documents, hints, cik=cik)
    return Phase2FilingAcquisitionResult(
        documents=documents,
        hints=hints,
        inventory_frame=pd.DataFrame(inventory_rows_by_accession.values()).sort_values(
            ["filing_date", "filing_type", "accession_number"],
            ascending=[False, True, True],
            ignore_index=True,
        ),
        screening_frame=pd.DataFrame(screening_rows),
        metrics=metrics,
    )


def _screening_rows(documents: list[FilingDocument], hints: list[ESPPFilingHint], cik: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for document, hint in zip(documents, hints):
        rows.append(
            {
                "ticker": hint.ticker,
                "cik": cik,
                "source_mode": hint.source_kind,
                "source_id": hint.source_id,
                "accession_number": document.accession_number or hint.source_id,
                "filing_type": hint.filing_type,
                "filing_date": hint.filing_date.isoformat(),
                "report_date": document.report_date.isoformat() if document.report_date else None,
                "espp_mention_flag": bool(hint.matched_terms or hint.confidence > 0),
                "confidence": float(hint.confidence),
                "matched_terms": " | ".join(hint.matched_terms),
                "matched_term_count": len(hint.matched_terms),
                "contextual_snippets": " | ".join(hint.snippets),
                "snippet_count": len(hint.snippets),
                "month_day_candidates": " | ".join(f"{month:02d}-{day:02d}" for month, day in hint.month_day_candidates),
            }
        )
    return rows


def _read_or_fetch_json(
    client: SecHttpClient,
    cache_path: Path,
    url: str,
    cache_only: bool,
    metrics: FilingAcquisitionMetrics,
    hit_field: str,
    miss_field: str,
    label: str,
) -> tuple[dict[str, object], str]:
    payload, source = _read_or_fetch_text(
        client=client,
        cache_path=cache_path,
        url=url,
        cache_only=cache_only,
        metrics=metrics,
        hit_field=hit_field,
        miss_field=miss_field,
        label=label,
    )
    return json.loads(payload), source


def _read_or_fetch_text(
    client: SecHttpClient,
    cache_path: Path,
    url: str,
    cache_only: bool,
    metrics: FilingAcquisitionMetrics,
    hit_field: str,
    miss_field: str,
    label: str,
) -> tuple[str, str]:
    if cache_path.exists():
        setattr(metrics, hit_field, getattr(metrics, hit_field) + 1)
        return cache_path.read_text(encoding="utf-8"), "cache"
    if cache_only:
        raise FileNotFoundError(f"Cache-only mode missing {label} cache at {cache_path}")
    payload = client.get_text(url, metrics=metrics)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(payload, encoding="utf-8")
    setattr(metrics, miss_field, getattr(metrics, miss_field) + 1)
    return payload, "network"


def _submissions_cache_path(cache_root: Path, cik: str) -> Path:
    return cache_root / "submissions" / f"CIK{cik}.json"


def _submissions_history_cache_path(cache_root: Path, file_name: str) -> Path:
    return cache_root / "submissions" / Path(file_name).name


def _filing_directory(cache_root: Path, cik: str, accession_nodashes: str) -> Path:
    return cache_root / "filings" / cik / accession_nodashes


def _select_filing_metadata(
    submissions_payload: dict[str, object],
    filing_config: SECFilingSourceConfig,
    client: SecHttpClient,
    cache_root: Path,
    ticker: str,
    cik: str,
    company_name: str,
    metrics: FilingAcquisitionMetrics,
) -> list[SecFilingMetadata]:
    metadata_rows = _metadata_from_payload(
        submissions_payload,
        ticker=ticker,
        cik=cik,
        company_name=company_name,
        default_source_file=f"CIK{cik}.json",
    )

    for file_entry in submissions_payload.get("filings", {}).get("files", []):
        if not isinstance(file_entry, dict):
            continue
        name = str(file_entry.get("name", "")).strip()
        if not name:
            continue
        extra_payload, _ = _read_or_fetch_json(
            client=client,
            cache_path=_submissions_history_cache_path(cache_root, name),
            url=f"{DATA_SEC_SUBMISSIONS_URL}/{name}",
            cache_only=filing_config.cache_only,
            metrics=metrics,
            hit_field="submissions_cache_hits",
            miss_field="submissions_cache_misses",
            label=f"historical submissions JSON {name}",
        )
        metadata_rows.extend(
            _metadata_from_payload(
                extra_payload,
                ticker=ticker,
                cik=cik,
                company_name=company_name,
                default_source_file=name,
            )
        )

    deduped: dict[str, SecFilingMetadata] = {}
    for row in metadata_rows:
        deduped.setdefault(row.accession_number, row)

    return sorted(
        deduped.values(),
        key=lambda item: (item.filing_date, item.form, item.accession_number),
        reverse=True,
    )


def _metadata_from_payload(
    payload: dict[str, object],
    ticker: str,
    cik: str,
    company_name: str,
    default_source_file: str,
) -> list[SecFilingMetadata]:
    table = payload.get("filings", {}).get("recent")
    if not isinstance(table, dict):
        table = payload
    accessions = table.get("accessionNumber", [])
    filing_dates = table.get("filingDate", [])
    forms = table.get("form", [])
    primary_documents = table.get("primaryDocument", [])
    descriptions = table.get("primaryDocDescription", [])
    report_dates = table.get("reportDate", [])

    rows: list[SecFilingMetadata] = []
    for index, accession in enumerate(accessions):
        filing_date = filing_dates[index] if index < len(filing_dates) else None
        form = forms[index] if index < len(forms) else ""
        primary_document = primary_documents[index] if index < len(primary_documents) else ""
        description = descriptions[index] if index < len(descriptions) else ""
        report_date = report_dates[index] if index < len(report_dates) else None
        accession_str = str(accession).strip()
        if not accession_str or not filing_date:
            continue
        rows.append(
            SecFilingMetadata(
                ticker=ticker,
                cik=cik,
                company_name=company_name,
                accession_number=accession_str,
                accession_nodashes=accession_str.replace("-", ""),
                form=str(form).strip(),
                filing_date=date.fromisoformat(str(filing_date)),
                report_date=date.fromisoformat(str(report_date)) if report_date else None,
                primary_document=str(primary_document).strip(),
                primary_doc_description=str(description).strip(),
                submission_source_file=default_source_file,
            )
        )
    return rows


def _download_sec_filing(
    filing_config: SECFilingSourceConfig,
    cache_root: Path,
    client: SecHttpClient,
    metadata: SecFilingMetadata,
    metrics: FilingAcquisitionMetrics,
) -> tuple[FilingDocument, ESPPFilingHint, dict[str, object]]:
    filing_dir = _filing_directory(cache_root, metadata.cik, metadata.accession_nodashes)
    index_payload, index_source = _read_or_fetch_json(
        client=client,
        cache_path=filing_dir / "index.json",
        url=metadata.index_url,
        cache_only=filing_config.cache_only,
        metrics=metrics,
        hit_field="index_cache_hits",
        miss_field="index_cache_misses",
        label=f"index metadata for {metadata.accession_number}",
    )
    primary_document_name = _resolve_primary_document_name(metadata, index_payload)
    document_path = filing_dir / primary_document_name
    document_url = f"{metadata.filing_directory_url}/{primary_document_name}"
    raw_document, document_source = _read_or_fetch_text(
        client=client,
        cache_path=document_path,
        url=document_url,
        cache_only=filing_config.cache_only,
        metrics=metrics,
        hit_field="document_cache_hits",
        miss_field="document_cache_misses",
        label=f"primary filing document for {metadata.accession_number}",
    )
    (filing_dir / "metadata.json").write_text(
        json.dumps(
            {
                "ticker": metadata.ticker,
                "cik": metadata.cik,
                "company_name": metadata.company_name,
                "accession_number": metadata.accession_number,
                "form": metadata.form,
                "filing_date": metadata.filing_date.isoformat(),
                "report_date": metadata.report_date.isoformat() if metadata.report_date else None,
                "primary_document": primary_document_name,
                "primary_doc_description": metadata.primary_doc_description,
                "document_url": document_url,
                "index_url": metadata.index_url,
                "submission_source_file": metadata.submission_source_file,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    cleaned_text = _normalize_filing_text(raw_document)
    document = FilingDocument(
        ticker=metadata.ticker,
        filing_type=metadata.form,
        filing_date=metadata.filing_date,
        text=cleaned_text,
        source_id=metadata.accession_number,
        source_kind="sec",
        source_url=document_url,
        source_cache_path=str(document_path),
        accession_number=metadata.accession_number,
        report_date=metadata.report_date,
        issuer_name=metadata.company_name,
        cik=metadata.cik,
    )
    hint = extract_espp_hints(document)
    inventory_row = {
        "ticker": metadata.ticker,
        "cik": metadata.cik,
        "source_mode": "sec",
        "source_id": metadata.accession_number,
        "accession_number": metadata.accession_number,
        "filing_type": metadata.form,
        "filing_date": metadata.filing_date.isoformat(),
        "report_date": metadata.report_date.isoformat() if metadata.report_date else None,
        "primary_document": primary_document_name,
        "primary_doc_description": metadata.primary_doc_description,
        "filing_url": document_url,
        "index_url": metadata.index_url,
        "document_cache_path": str(document_path),
        "configured_filing_start_date": filing_config.filing_start_date.isoformat() if filing_config.filing_start_date else None,
        "configured_filing_end_date": filing_config.filing_end_date.isoformat() if filing_config.filing_end_date else None,
        "effective_filing_start_date": metrics.effective_filing_start_date.isoformat() if metrics.effective_filing_start_date else None,
        "effective_filing_end_date": metrics.effective_filing_end_date.isoformat() if metrics.effective_filing_end_date else None,
        "matches_form_filter": _matches_form_filter(metadata.form, filing_config),
        "in_filing_date_window": _in_filing_date_window(metadata.filing_date, filing_config),
        "selected_after_safety_cap": True,
        "screening_passed": bool(hint.matched_terms or hint.confidence > 0),
        "submissions_source": metadata.submission_source_file,
        "index_source": index_source,
        "document_source": document_source,
        "processed_successfully": True,
        "warning": "",
    }
    return document, hint, inventory_row


def _resolve_primary_document_name(metadata: SecFilingMetadata, index_payload: dict[str, object]) -> str:
    candidates: list[str] = []
    if metadata.primary_document:
        candidates.append(metadata.primary_document)
    directory = index_payload.get("directory", {})
    for item in directory.get("item", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        candidates.append(name)
    preferred_extensions = (".htm", ".html", ".txt")
    for candidate in candidates:
        if candidate.lower().endswith(preferred_extensions):
            return Path(candidate).name
    if candidates:
        return Path(candidates[0]).name
    raise ValueError(f"No primary filing document discovered for {metadata.accession_number}")


def _normalize_filing_text(raw_document: str) -> str:
    without_scripts = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw_document)
    without_tags = re.sub(r"(?is)<[^>]+>", " ", without_scripts)
    collapsed = re.sub(r"\s+", " ", unescape(without_tags)).strip()
    return collapsed or raw_document
