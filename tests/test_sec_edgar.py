from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.error import HTTPError

from src.sec.edgar import FilingAcquisitionMetrics, SECFilingSourceConfig, SecHttpClient, build_sec_http_client, load_batch_filing_inputs


class _FakeHTTPResponse:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _sec_routes() -> dict[str, str]:
    submissions_url = "https://data.sec.gov/submissions/CIK0000320193.json"
    base_url = "https://www.sec.gov/Archives/edgar/data/320193"
    accession_10k = "0000320193-24-000069"
    accession_proxy = "0000320193-24-000055"
    index_10k = f"{base_url}/{accession_10k.replace('-', '')}/index.json"
    doc_10k = f"{base_url}/{accession_10k.replace('-', '')}/aapl-20240928x10k.htm"
    index_proxy = f"{base_url}/{accession_proxy.replace('-', '')}/index.json"
    doc_proxy = f"{base_url}/{accession_proxy.replace('-', '')}/def14a2024.htm"
    return {
        submissions_url: "\n".join(
            [
                "{",
                '  "cik": "0000320193",',
                '  "filings": {"recent": {',
                '    "accessionNumber": ["0000320193-24-000069", "0000320193-24-000055"],',
                '    "filingDate": ["2024-11-01", "2024-01-26"],',
                '    "form": ["10-K", "DEF 14A"],',
                '    "primaryDocument": ["aapl-20240928x10k.htm", "def14a2024.htm"],',
                '    "primaryDocDescription": ["10-K", "DEF 14A"]',
                '  }, "files": []}',
                "}",
            ]
        ),
        index_10k: '{"directory": {"item": [{"name": "aapl-20240928x10k.htm"}]}}',
        doc_10k: "<html><body>Employee Stock Purchase Plan purchase dates occur on June 30 and December 31.</body></html>",
        index_proxy: '{"directory": {"item": [{"name": "def14a2024.htm"}]}}',
        doc_proxy: "<html><body>The employee stock purchase plan has an offering period and a January 1 purchase date.</body></html>",
    }


def _fake_opener(routes: dict[str, str], request_headers: list[dict[str, str]] | None = None, failures: dict[str, list[object]] | None = None):
    def _opener(request, timeout=None):
        if request_headers is not None:
            request_headers.append(dict(request.header_items()))
        url = request.full_url
        if failures and url in failures and failures[url]:
            next_result = failures[url].pop(0)
            if isinstance(next_result, Exception):
                raise next_result
        if url not in routes:
            raise AssertionError(f"Unexpected URL requested: {url}")
        return _FakeHTTPResponse(routes[url])

    return _opener


def test_load_batch_filing_inputs_fetches_sec_filings_and_populates_cache(tmp_path: Path, monkeypatch) -> None:
    routes = _sec_routes()
    request_headers: list[dict[str, str]] = []

    import src.sec.edgar as sec_edgar

    monkeypatch.setattr(
        sec_edgar,
        "build_sec_http_client",
        lambda config: sec_edgar.SecHttpClient(
            user_agent=str(config.sec_user_agent),
            request_delay_seconds=float(config.request_delay_seconds),
            max_retries=int(config.max_retries),
            timeout_seconds=float(config.timeout_seconds),
            opener=_fake_opener(routes, request_headers=request_headers),
            sleep_func=lambda seconds: None,
            clock=lambda: 1.0,
        ),
    )

    result = load_batch_filing_inputs(
        filing_config=SECFilingSourceConfig(
            source="sec",
            sec_user_agent="Test Company test@example.com",
            forms=("10-K", "DEF 14A"),
            max_filings_per_issuer=2,
            cache_only=False,
            request_delay_seconds=0.2,
            max_retries=2,
            timeout_seconds=5.0,
        ),
        cache_dir=tmp_path / "cache",
        ticker="AAPL",
        cik="0000320193",
        company_name="Apple Inc.",
    )

    assert len(result.documents) == 2
    assert result.metrics.filings_discovered == 2
    assert result.metrics.filings_selected == 2
    assert result.metrics.filings_processed == 2
    assert result.metrics.cache_hits_total == 0
    assert result.metrics.cache_misses_total == 5
    assert "employee stock purchase plan" in result.screening_frame["matched_terms"].iloc[0]
    assert result.inventory_frame["document_source"].tolist() == ["network", "network"]
    assert any(headers.get("User-agent") == "Test Company test@example.com" for headers in request_headers)
    assert (tmp_path / "cache" / "submissions" / "CIK0000320193.json").exists()
    assert (
        tmp_path
        / "cache"
        / "filings"
        / "0000320193"
        / "000032019324000069"
        / "aapl-20240928x10k.htm"
    ).exists()


def test_load_batch_filing_inputs_cache_only_uses_existing_cache(tmp_path: Path, monkeypatch) -> None:
    routes = _sec_routes()

    import src.sec.edgar as sec_edgar

    monkeypatch.setattr(
        sec_edgar,
        "build_sec_http_client",
        lambda config: sec_edgar.SecHttpClient(
            user_agent=str(config.sec_user_agent),
            request_delay_seconds=float(config.request_delay_seconds),
            max_retries=int(config.max_retries),
            timeout_seconds=float(config.timeout_seconds),
            opener=_fake_opener(routes),
            sleep_func=lambda seconds: None,
            clock=lambda: 1.0,
        ),
    )
    live_config = SECFilingSourceConfig(
        source="sec",
        sec_user_agent="Test Company test@example.com",
        forms=("10-K", "DEF 14A"),
        max_filings_per_issuer=2,
        cache_only=False,
        request_delay_seconds=0.2,
        max_retries=2,
        timeout_seconds=5.0,
    )
    cache_dir = tmp_path / "cache"
    load_batch_filing_inputs(live_config, cache_dir=cache_dir, ticker="AAPL", cik="0000320193", company_name="Apple Inc.")

    monkeypatch.setattr(
        sec_edgar,
        "build_sec_http_client",
        lambda config: sec_edgar.SecHttpClient(
            user_agent=str(config.sec_user_agent),
            request_delay_seconds=float(config.request_delay_seconds),
            max_retries=int(config.max_retries),
            timeout_seconds=float(config.timeout_seconds),
            opener=lambda request, timeout=None: (_ for _ in ()).throw(AssertionError("Network should not be used in cache-only mode")),
            sleep_func=lambda seconds: None,
            clock=lambda: 1.0,
        ),
    )
    cache_only_result = load_batch_filing_inputs(
        SECFilingSourceConfig(
            source="sec",
            sec_user_agent="Test Company test@example.com",
            forms=("10-K", "DEF 14A"),
            max_filings_per_issuer=2,
            cache_only=True,
            request_delay_seconds=0.2,
            max_retries=2,
            timeout_seconds=5.0,
        ),
        cache_dir=cache_dir,
        ticker="AAPL",
        cik="0000320193",
        company_name="Apple Inc.",
    )

    assert len(cache_only_result.documents) == 2
    assert cache_only_result.metrics.cache_hits_total == 5
    assert cache_only_result.metrics.cache_misses_total == 0
    assert cache_only_result.inventory_frame["document_source"].tolist() == ["cache", "cache"]


def test_build_sec_http_client_allows_cache_only_placeholder_user_agent() -> None:
    client = build_sec_http_client(
        SECFilingSourceConfig(
            source="sec",
            sec_user_agent=None,
            cache_only=True,
            request_delay_seconds=0.2,
            max_retries=2,
            timeout_seconds=5.0,
        )
    )

    assert client.user_agent == "cache-only-replay"


def test_sec_http_client_retries_retryable_http_errors() -> None:
    request_headers: list[dict[str, str]] = []
    routes = {"https://data.sec.gov/submissions/CIK0000320193.json": '{"ok": true}'}
    failures = {
        "https://data.sec.gov/submissions/CIK0000320193.json": [
            HTTPError(
                url="https://data.sec.gov/submissions/CIK0000320193.json",
                code=429,
                msg="Too Many Requests",
                hdrs=None,
                fp=None,
            )
        ]
    }
    sleeps: list[float] = []
    metrics = FilingAcquisitionMetrics(ticker="AAPL", cik="0000320193", source_mode="sec", cache_only=False)
    clock_values = iter([1.0, 1.2, 1.4])
    client = SecHttpClient(
        user_agent="Retry Test retry@example.com",
        request_delay_seconds=0.2,
        max_retries=2,
        timeout_seconds=5.0,
        opener=_fake_opener(routes, request_headers=request_headers, failures=failures),
        sleep_func=sleeps.append,
        clock=lambda: next(clock_values),
    )

    payload = client.get_json("https://data.sec.gov/submissions/CIK0000320193.json", metrics=metrics)

    assert payload == {"ok": True}
    assert metrics.retry_count == 1
    assert abs(sleeps[0] - 0.2) < 1e-9
    assert all(abs(value) < 1e-9 for value in sleeps[1:])
    assert any(headers.get("User-agent") == "Retry Test retry@example.com" for headers in request_headers)


def test_load_batch_filing_inputs_applies_date_window_before_safety_cap(tmp_path: Path, monkeypatch) -> None:
    submissions_url = "https://data.sec.gov/submissions/CIK0000320193.json"
    base_url = "https://www.sec.gov/Archives/edgar/data/320193"
    accessions = [
        "0000320193-24-000069",
        "0000320193-24-000055",
        "0000320193-23-000099",
    ]
    routes = {
        submissions_url: "\n".join(
            [
                "{",
                '  "cik": "0000320193",',
                '  "filings": {"recent": {',
                '    "accessionNumber": ["0000320193-24-000069", "0000320193-24-000055", "0000320193-23-000099"],',
                '    "filingDate": ["2024-11-01", "2024-01-26", "2023-01-20"],',
                '    "reportDate": ["2024-09-28", "2023-12-30", "2022-12-31"],',
                '    "form": ["10-K", "DEF 14A", "10-K"],',
                '    "primaryDocument": ["aapl-20240928x10k.htm", "def14a2024.htm", "aapl-20221231x10k.htm"],',
                '    "primaryDocDescription": ["10-K", "DEF 14A", "10-K"]',
                '  }, "files": []}',
                "}",
            ]
        ),
    }
    for accession, document_name in (
        (accessions[0], "aapl-20240928x10k.htm"),
        (accessions[1], "def14a2024.htm"),
    ):
        accession_no_dashes = accession.replace("-", "")
        routes[f"{base_url}/{accession_no_dashes}/index.json"] = f'{{"directory": {{"item": [{{"name": "{document_name}"}}]}}}}'
        routes[f"{base_url}/{accession_no_dashes}/{document_name}"] = (
            "<html><body>Employee Stock Purchase Plan purchase dates occur on June 30 and December 31.</body></html>"
        )

    import src.sec.edgar as sec_edgar

    monkeypatch.setattr(
        sec_edgar,
        "build_sec_http_client",
        lambda config: sec_edgar.SecHttpClient(
            user_agent=str(config.sec_user_agent),
            request_delay_seconds=float(config.request_delay_seconds),
            max_retries=int(config.max_retries),
            timeout_seconds=float(config.timeout_seconds),
            opener=_fake_opener(routes),
            sleep_func=lambda seconds: None,
            clock=lambda: 1.0,
        ),
    )

    result = load_batch_filing_inputs(
        filing_config=SECFilingSourceConfig(
            source="sec",
            sec_user_agent="Test Company test@example.com",
            forms=("10-K", "DEF 14A"),
            filing_start_date=date.fromisoformat("2024-01-01"),
            filing_end_date=date.fromisoformat("2024-12-31"),
            max_filings_per_issuer=1,
            cache_only=False,
            request_delay_seconds=0.2,
            max_retries=2,
            timeout_seconds=5.0,
        ),
        cache_dir=tmp_path / "cache",
        ticker="AAPL",
        cik="0000320193",
        company_name="Apple Inc.",
    )

    assert result.metrics.filings_discovered == 3
    assert result.metrics.filings_matching_forms == 3
    assert result.metrics.filings_in_date_window == 2
    assert result.metrics.filings_selected == 1
    assert result.metrics.filings_processed == 1
    assert result.inventory_frame["matches_form_filter"].tolist() == [True, True, True]
    assert result.inventory_frame["in_filing_date_window"].tolist() == [True, True, False]
    assert result.inventory_frame["selected_after_safety_cap"].tolist() == [True, False, False]
