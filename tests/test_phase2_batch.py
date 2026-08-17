import sys
import types
from pathlib import Path

import pandas as pd
import pytest

matplotlib = types.ModuleType("matplotlib")
pyplot = types.ModuleType("pyplot")


class _DummyAxes:
    def plot(self, *args, **kwargs) -> None:
        return None

    def axhline(self, *args, **kwargs) -> None:
        return None

    def set_title(self, *args, **kwargs) -> None:
        return None

    def set_xlabel(self, *args, **kwargs) -> None:
        return None

    def set_ylabel(self, *args, **kwargs) -> None:
        return None

    def legend(self, *args, **kwargs) -> None:
        return None


class _DummyFigure:
    def tight_layout(self) -> None:
        return None


def _dummy_subplots(*args, **kwargs):
    return _DummyFigure(), _DummyAxes()


pyplot.Figure = object
pyplot.subplots = _dummy_subplots
matplotlib.pyplot = pyplot
sys.modules.setdefault("matplotlib", matplotlib)
sys.modules.setdefault("matplotlib.pyplot", pyplot)

from src.pipeline.batch_config import load_batch_config
from src.pipeline.company_status import CompanyProcessingStatus, write_status_frame
from src.pipeline.run_batch import STATUS_FILE_NAME, run_phase2_batch


def _write_fixture_dir(tmp_path: Path) -> Path:
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    (fixture_dir / "aapl.yaml").write_text(
        "\n".join(
            [
                "ticker: AAPL",
                "filing_type: 10-K",
                'filing_date: "2024-02-15"',
                "source_id: aapl_fixture",
                "text: |",
                "  Employee Stock Purchase Plan purchase dates occur on June 30 and December 31.",
            ]
        ),
        encoding="utf-8",
    )
    (fixture_dir / "crm.yaml").write_text(
        "\n".join(
            [
                "ticker: CRM",
                "filing_type: 10-K",
                'filing_date: "2024-03-01"',
                "source_id: crm_fixture",
                "text: |",
                "  Employee Stock Purchase Plan purchase dates occur on June 30 and December 31.",
            ]
        ),
        encoding="utf-8",
    )
    return fixture_dir


def _write_price_file(tmp_path: Path, include_crm: bool = True) -> Path:
    lines = [
        "ticker,date,open,high,low,close,volume",
        "AAPL,2024-06-28,100,101,99,100,1000000",
        "AAPL,2024-06-29,101,102,100,101,900000",
        "AAPL,2024-06-30,102,103,101,102,800000",
        "AAPL,2024-07-01,103,104,102,103,2500000",
        "AAPL,2024-12-30,110,111,109,110,1000000",
        "AAPL,2024-12-31,111,112,110,111,2300000",
        "AAPL,2025-01-01,112,113,111,112,900000",
    ]
    if include_crm:
        lines.extend(
            [
                "CRM,2024-06-28,200,201,199,200,900000",
                "CRM,2024-06-29,201,202,200,201,850000",
                "CRM,2024-06-30,202,203,201,202,800000",
                "CRM,2024-07-01,203,204,202,203,2200000",
                "CRM,2024-12-30,210,211,209,210,1000000",
                "CRM,2024-12-31,211,212,210,211,900000",
                "CRM,2025-01-01,212,213,211,212,850000",
            ]
        )
    lines.extend(
        [
            "SPY,2024-06-28,300,301,299,300,1500000",
            "SPY,2024-06-29,301,302,300,301,1500000",
            "SPY,2024-06-30,302,303,301,302,1500000",
            "SPY,2024-07-01,303,304,302,303,1500000",
            "SPY,2024-12-30,310,311,309,310,1500000",
            "SPY,2024-12-31,311,312,310,311,1500000",
            "SPY,2025-01-01,312,313,311,312,1500000",
        ]
    )
    price_path = tmp_path / "prices.csv"
    price_path.write_text("\n".join(lines), encoding="utf-8")
    return price_path


def _write_universe_file(tmp_path: Path) -> Path:
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "\n".join(
            [
                "ticker,company_name,issuer_name,issuer_id,cik,gics_sector,gics_sub_industry,primary_ticker,is_primary_share_class",
                "AAPL,Apple Inc.,Apple Inc.,apple-inc,320193,Information Technology,Technology Hardware Storage & Peripherals,AAPL,true",
                "CRM,Salesforce Inc.,Salesforce Inc.,salesforce-inc,1108524,Information Technology,Application Software,CRM,true",
                "CRMA,Salesforce Inc. (Class B),Salesforce Inc.,salesforce-inc,1108524,Information Technology,Application Software,CRM,false",
            ]
        ),
        encoding="utf-8",
    )
    return universe_path


def _write_review_file(tmp_path: Path) -> Path:
    review_path = tmp_path / "reviews.csv"
    review_path.write_text(
        "\n".join(
            [
                "event_review_id,ticker,original_assigned_event_date,reviewed_event_date,review_status,review_note",
                "AAPL|10-K|2024-02-15|aapl_fixture|06-30|2024-06-30|filing_text_month_day,AAPL,2024-06-30,,accepted,Keep the summer event",
                "CRM|10-K|2024-03-01|crm_fixture|12-31|2024-12-31|filing_text_month_day,CRM,2024-12-31,,rejected,Reject the year-end event",
            ]
        ),
        encoding="utf-8",
    )
    return review_path


def _write_config(
    tmp_path: Path,
    universe_path: Path,
    price_path: Path,
    fixture_dir: Path,
    review_path: Path | None,
    output_dir: Path,
    resume_mode: bool = False,
    ) -> Path:
    config_path = tmp_path / "phase2.yaml"
    review_line = f'  review_file: "{review_path.as_posix()}"' if review_path else "  review_file: null"
    config_path.write_text(
        "\n".join(
            [
                'benchmark: "SPY"',
                f'universe_file: "{universe_path.as_posix()}"',
                'ticker_subset: ["AAPL", "CRM", "CRMA"]',
                'sector_subset: ["Information Technology"]',
                'start_date: "2024-06-28"',
                'end_date: "2025-01-01"',
                f'output_dir: "{output_dir.as_posix()}"',
                f'cache_dir: "{(tmp_path / "cache").as_posix()}"',
                f"resume_mode: {'true' if resume_mode else 'false'}",
                "offline_mode: true",
                "max_companies: 3",
                'price_source: "csv"',
                f'price_data_path: "{price_path.as_posix()}"',
                "filings:",
                f'  fixture_dir: "{fixture_dir.as_posix()}"',
                "reviews:",
                review_line,
                "event_study:",
                "  window_before: 0",
                "  window_after: 1",
                "  volume_lookback: 5",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def _write_sec_config(
    tmp_path: Path,
    universe_path: Path,
    price_path: Path,
    output_dir: Path,
    include_user_agent: bool = True,
    cache_only: bool = False,
) -> Path:
    config_path = tmp_path / "phase2_live_sec.yaml"
    sec_user_agent_lines = ['  sec_user_agent: "Test Company test@example.com"'] if include_user_agent else []
    config_path.write_text(
        "\n".join(
            [
                'benchmark: "SPY"',
                f'universe_file: "{universe_path.as_posix()}"',
                'ticker_subset: ["AAPL"]',
                'start_date: "2024-06-28"',
                'end_date: "2025-01-01"',
                f'output_dir: "{output_dir.as_posix()}"',
                f'cache_dir: "{(tmp_path / "cache").as_posix()}"',
                "resume_mode: false",
                "offline_mode: false",
                "max_companies: 1",
                'price_source: "csv"',
                f'price_data_path: "{price_path.as_posix()}"',
                "filings:",
                '  source: "sec"',
                *sec_user_agent_lines,
                "  forms:",
                '    - "10-K"',
                '    - "DEF 14A"',
                "  max_filings_per_issuer: 2",
                f"  cache_only: {'true' if cache_only else 'false'}",
                "  request_delay_seconds: 0.2",
                "  max_retries: 2",
                "  timeout_seconds: 5",
                "reviews:",
                "  review_file: null",
                "event_study:",
                "  window_before: 0",
                "  window_after: 1",
                "  volume_lookback: 5",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def _write_phase3_config(
    tmp_path: Path,
    universe_path: Path,
    price_path: Path,
    fixture_dir: Path,
    review_path: Path | None,
    output_dir: Path,
    resume_mode: bool = False,
    event_study_enabled: bool = True,
    auto_policy_review: bool = False,
    review_as_of_date: str | None = None,
) -> Path:
    config_path = tmp_path / "phase3.yaml"
    review_line = f'  review_file: "{review_path.as_posix()}"' if review_path else "  review_file: null"
    review_as_of_date_lines = [f'  review_as_of_date: "{review_as_of_date}"'] if review_as_of_date else []
    config_path.write_text(
        "\n".join(
            [
                'benchmark: "SPY"',
                f'universe_file: "{universe_path.as_posix()}"',
                'ticker_subset: ["AAPL"]',
                'start_date: "2024-06-28"',
                'end_date: "2025-01-01"',
                f'output_dir: "{output_dir.as_posix()}"',
                f'cache_dir: "{(tmp_path / "cache").as_posix()}"',
                f"resume_mode: {'true' if resume_mode else 'false'}",
                "offline_mode: true",
                "max_companies: 1",
                'price_source: "csv"',
                f'price_data_path: "{price_path.as_posix()}"',
                "filings:",
                '  source: "fixture"',
                f'  fixture_dir: "{fixture_dir.as_posix()}"',
                "  forms:",
                '    - "10-K"',
                '    - "DEF 14A"',
                '  filing_start_date: "2024-01-01"',
                '  filing_end_date: "2024-12-31"',
                "  max_filings_per_issuer: 4",
                "  cache_only: false",
                "  request_delay_seconds: 0.2",
                "  max_retries: 0",
                "  timeout_seconds: 30",
                "reviews:",
                review_line,
                "phase3:",
                "  enabled: true",
                "  screened_only: true",
                "  diagnostic_extract_from_unscreened_filings: false",
                "  context_window_chars: 180",
                "  require_review_for_validated_windows: true",
                "  generate_provisional_unreviewed_windows: false",
                f"  auto_policy_review: {'true' if auto_policy_review else 'false'}",
                *review_as_of_date_lines,
                "event_study:",
                f"  enabled: {'true' if event_study_enabled else 'false'}",
                "  window_before: 0",
                "  window_after: 0",
                "  volume_lookback: 5",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


class _FakeHTTPResponse:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _sec_fake_routes() -> dict[str, str]:
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
        doc_proxy: "<html><body>The employee stock purchase plan has an offering period with a January 1 purchase date.</body></html>",
    }


def _fake_sec_opener(routes: dict[str, str]):
    def _opener(request, timeout=None):
        url = request.full_url
        if url not in routes:
            raise AssertionError(f"Unexpected SEC URL requested: {url}")
        return _FakeHTTPResponse(routes[url])

    return _opener


def test_load_batch_config_parses_paths_and_subsets(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path=tmp_path,
        universe_path=tmp_path / "universe.csv",
        price_path=tmp_path / "prices.csv",
        fixture_dir=tmp_path / "fixtures",
        review_path=None,
        output_dir=tmp_path / "artifacts",
        resume_mode=True,
    )

    config = load_batch_config(config_path)

    assert config.resume_mode is True
    assert config.offline_mode is True
    assert config.max_companies == 3
    assert config.ticker_subset == ["AAPL", "CRM", "CRMA"]
    assert config.sector_subset == ["Information Technology"]
    assert config.filings.source == "fixture"


def test_load_batch_config_accepts_sec_user_agent_from_environment(tmp_path: Path, monkeypatch) -> None:
    config_path = _write_sec_config(
        tmp_path=tmp_path,
        universe_path=tmp_path / "universe.csv",
        price_path=tmp_path / "prices.csv",
        output_dir=tmp_path / "artifacts",
        include_user_agent=False,
    )
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "Env Test env@example.com")

    config = load_batch_config(config_path)

    assert config.filings.source == "sec"
    assert config.filings.sec_user_agent == "Env Test env@example.com"


def test_load_batch_config_allows_cache_only_sec_without_user_agent(tmp_path: Path) -> None:
    config_path = _write_sec_config(
        tmp_path=tmp_path,
        universe_path=tmp_path / "universe.csv",
        price_path=tmp_path / "prices.csv",
        output_dir=tmp_path / "artifacts",
        include_user_agent=False,
        cache_only=True,
    )

    config = load_batch_config(config_path)

    assert config.filings.source == "sec"
    assert config.filings.cache_only is True
    assert config.filings.sec_user_agent is None


def test_load_batch_config_parses_phase3_policy_review_and_event_study_toggle(tmp_path: Path) -> None:
    fixture_dir = _write_fixture_dir(tmp_path)
    price_path = _write_price_file(tmp_path)
    universe_path = _write_universe_file(tmp_path)
    config_path = _write_phase3_config(
        tmp_path=tmp_path,
        universe_path=universe_path,
        price_path=price_path,
        fixture_dir=fixture_dir,
        review_path=None,
        output_dir=tmp_path / "artifacts",
        event_study_enabled=False,
        auto_policy_review=True,
        review_as_of_date="2026-08-17",
    )

    config = load_batch_config(config_path)

    assert config.event_study_enabled is False
    assert config.phase3.auto_policy_review is True
    assert config.phase3.review_as_of_date.isoformat() == "2026-08-17"


def test_run_phase2_batch_writes_status_summary_and_skips_secondary_share_class(tmp_path: Path) -> None:
    fixture_dir = _write_fixture_dir(tmp_path)
    price_path = _write_price_file(tmp_path, include_crm=True)
    universe_path = _write_universe_file(tmp_path)
    review_path = _write_review_file(tmp_path)
    output_dir = tmp_path / "artifacts"
    config_path = _write_config(tmp_path, universe_path, price_path, fixture_dir, review_path, output_dir)

    run_phase2_batch(config_path)

    status = pd.read_csv(output_dir / STATUS_FILE_NAME)
    audit = pd.read_csv(output_dir / "espp_date_audit.csv")
    summary_text = (output_dir / "reports" / "phase2_research_summary.md").read_text(encoding="utf-8")

    assert status["ticker"].tolist() == ["AAPL", "CRM", "CRMA"]
    assert status.loc[status["ticker"] == "AAPL", "processing_status"].iloc[0] == "completed"
    assert status.loc[status["ticker"] == "CRM", "processing_status"].iloc[0] == "completed"
    assert status.loc[status["ticker"] == "CRMA", "processing_status"].iloc[0] == "skipped"
    assert "CRMA" not in audit["ticker"].tolist()
    assert "Preliminary research infrastructure output" in summary_text
    assert "survivorship and index-selection bias" in summary_text
    assert (output_dir / "phase2_summary_metrics.csv").exists()
    assert (output_dir / "phase2_sector_counts.csv").exists()


def test_run_phase2_batch_isolates_company_failures(tmp_path: Path) -> None:
    fixture_dir = _write_fixture_dir(tmp_path)
    price_path = _write_price_file(tmp_path, include_crm=False)
    universe_path = _write_universe_file(tmp_path)
    review_path = _write_review_file(tmp_path)
    output_dir = tmp_path / "artifacts"
    config_path = _write_config(tmp_path, universe_path, price_path, fixture_dir, review_path, output_dir)

    run_phase2_batch(config_path)

    status = pd.read_csv(output_dir / STATUS_FILE_NAME)
    windows = pd.read_csv(output_dir / "all_event_windows.csv")

    assert status.loc[status["ticker"] == "AAPL", "processing_status"].iloc[0] == "completed"
    assert status.loc[status["ticker"] == "CRM", "processing_status"].iloc[0] == "failed"
    assert sorted(set(windows["ticker"])) == ["AAPL"]


def test_run_phase2_batch_resume_mode_reprocesses_failed_only(tmp_path: Path, monkeypatch) -> None:
    fixture_dir = _write_fixture_dir(tmp_path)
    price_path = _write_price_file(tmp_path, include_crm=True)
    universe_path = _write_universe_file(tmp_path)
    review_path = _write_review_file(tmp_path)
    output_dir = tmp_path / "artifacts"
    config_path = _write_config(tmp_path, universe_path, price_path, fixture_dir, review_path, output_dir, resume_mode=True)

    output_dir.mkdir()
    existing_status = pd.DataFrame(
        [
            CompanyProcessingStatus(
                ticker="AAPL",
                company_name="Apple Inc.",
                cik="0000320193",
                sector="Information Technology",
                sub_industry="Technology Hardware Storage & Peripherals",
                issuer_id="apple-inc",
                primary_ticker="AAPL",
                is_primary_share_class=True,
                processing_status="completed",
                filings_discovered=1,
                filings_processed=1,
                espp_mentions_found=1,
                candidate_events_found=2,
                accepted_events=1,
                corrected_events=0,
                rejected_events=0,
                unresolved_events=2,
                future_scheduled_events=1,
                usable_event_windows=2,
                warning_count=0,
                processing_timestamp="2026-07-04T12:00:00+00:00",
            ).to_row(),
            CompanyProcessingStatus(
                ticker="CRM",
                company_name="Salesforce Inc.",
                cik="0001108524",
                sector="Information Technology",
                sub_industry="Application Software",
                issuer_id="salesforce-inc",
                primary_ticker="CRM",
                is_primary_share_class=True,
                processing_status="failed",
                error_message="stale failure",
                processing_timestamp="2026-07-04T12:01:00+00:00",
            ).to_row(),
        ]
    )
    write_status_frame(output_dir / STATUS_FILE_NAME, existing_status)
    pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "filing_type": "10-K",
                "filing_date": "2024-02-15",
                "source_fixture_path": "fixtures/aapl.yaml",
                "source_id": "aapl_fixture",
                "source_snippet": "employee stock purchase plan",
                "candidate_month_day": "06-30",
                "assigned_event_date": "2024-06-30",
                "derivation_rule": "filing_text_month_day",
                "confidence": 1.0,
                "fallback_anchor_used": False,
                "event_review_id": "AAPL|10-K|2024-02-15|aapl_fixture|06-30|2024-06-30|filing_text_month_day",
                "review_status": "accepted",
                "reviewed_event_date": None,
                "review_note": "Keep the summer event",
                "effective_event_date": "2024-06-30",
                "included_in_event_study": True,
            }
        ]
    ).to_csv(output_dir / "espp_date_audit.csv", index=False)
    pd.DataFrame(
        [
            {
                "event_id": 1,
                "event_date": "2024-06-30",
                "tau": 0,
                "close_price": 102.0,
                "raw_ret": 0.0099,
                "benchmark_ret": 0.0033,
                "abnormal_ret": 0.0066,
                "cum_ret": 0.0,
                "cum_abret": 0.0,
                "vol_ratio": 1.5,
                "ticker": "AAPL",
            }
        ]
    ).to_csv(output_dir / "all_event_windows.csv", index=False)

    import src.pipeline.run_batch as run_batch_module

    calls: list[str] = []

    def _fake_process_primary_company(company, config, loader, benchmark_prices, reviews):
        ticker = str(company["ticker"])
        calls.append(ticker)
        return run_batch_module.CompanyRunArtifacts(
            status=CompanyProcessingStatus(
                ticker=ticker,
                company_name=str(company["company_name"]),
                cik=str(company["cik"]),
                sector=str(company["gics_sector"]),
                sub_industry=str(company["gics_sub_industry"]),
                issuer_id=str(company["issuer_id"]),
                primary_ticker=str(company["primary_ticker"]),
                is_primary_share_class=bool(company["is_primary_share_class"]),
                processing_status="completed",
                filings_discovered=1,
                filings_processed=1,
                espp_mentions_found=1,
                candidate_events_found=1,
                usable_event_windows=1,
                processing_timestamp="2026-07-04T12:02:00+00:00",
            ),
            audit_frame=pd.DataFrame(
                [
                    {
                        "ticker": ticker,
                        "filing_type": "10-K",
                        "filing_date": "2024-03-01",
                        "source_fixture_path": "fixtures/crm.yaml",
                        "source_id": "crm_fixture",
                        "source_snippet": "employee stock purchase plan",
                        "candidate_month_day": "06-30",
                        "assigned_event_date": "2024-06-30",
                        "derivation_rule": "filing_text_month_day",
                        "confidence": 1.0,
                        "fallback_anchor_used": False,
                        "event_review_id": "CRM|10-K|2024-03-01|crm_fixture|06-30|2024-06-30|filing_text_month_day",
                        "review_status": "unreviewed",
                        "reviewed_event_date": None,
                        "review_note": None,
                        "effective_event_date": "2024-06-30",
                        "included_in_event_study": True,
                    }
                ]
            ),
            panel_frame=pd.DataFrame(
                [
                    {
                        "event_id": 1,
                        "event_date": "2024-06-30",
                        "tau": 0,
                        "close_price": 202.0,
                        "raw_ret": 0.0049,
                        "benchmark_ret": 0.0033,
                        "abnormal_ret": 0.0016,
                        "cum_ret": 0.0,
                        "cum_abret": 0.0,
                        "vol_ratio": 1.4,
                        "ticker": ticker,
                    }
                ]
            ),
        )

    monkeypatch.setattr(run_batch_module, "_process_primary_company", _fake_process_primary_company)

    run_phase2_batch(config_path)

    status = pd.read_csv(output_dir / STATUS_FILE_NAME)

    assert calls == ["CRM"]
    assert status.loc[status["ticker"] == "AAPL", "processing_status"].iloc[0] == "completed"
    assert status.loc[status["ticker"] == "AAPL", "unresolved_events"].iloc[0] == 2
    assert status.loc[status["ticker"] == "AAPL", "future_scheduled_events"].iloc[0] == 1
    assert status.loc[status["ticker"] == "CRM", "processing_status"].iloc[0] == "completed"


def test_run_phase2_batch_live_sec_mode_writes_sec_artifacts(tmp_path: Path, monkeypatch) -> None:
    price_path = _write_price_file(tmp_path, include_crm=False)
    universe_path = _write_universe_file(tmp_path)
    output_dir = tmp_path / "artifacts"
    config_path = _write_sec_config(tmp_path, universe_path, price_path, output_dir)

    import src.sec.edgar as sec_edgar

    monkeypatch.setattr(
        sec_edgar,
        "build_sec_http_client",
        lambda config: sec_edgar.SecHttpClient(
            user_agent=str(config.sec_user_agent),
            request_delay_seconds=float(config.request_delay_seconds),
            max_retries=int(config.max_retries),
            timeout_seconds=float(config.timeout_seconds),
            opener=_fake_sec_opener(_sec_fake_routes()),
            sleep_func=lambda seconds: None,
            clock=lambda: 1.0,
        ),
    )

    run_phase2_batch(config_path)

    status = pd.read_csv(output_dir / STATUS_FILE_NAME)
    inventory = pd.read_csv(output_dir / "filing_inventory.csv")
    screening = pd.read_csv(output_dir / "filing_screening_results.csv")
    metrics = pd.read_csv(output_dir / "sec_acquisition_metrics.csv")

    assert status["ticker"].tolist() == ["AAPL"]
    assert status.loc[0, "processing_status"] == "completed"
    assert status.loc[0, "filings_discovered"] == 2
    assert status.loc[0, "filings_processed"] == 2
    assert len(inventory) == 2
    assert inventory["processed_successfully"].tolist() == [True, True]
    assert screening["espp_mention_flag"].tolist() == [True, True]
    assert metrics.loc[0, "cache_misses_total"] == 5


def test_run_phase2_batch_reviewed_phase3_run_clears_stale_review_workflow_artifacts(tmp_path: Path, monkeypatch) -> None:
    fixture_dir = _write_fixture_dir(tmp_path)
    price_path = _write_price_file(tmp_path, include_crm=False)
    universe_path = _write_universe_file(tmp_path)
    output_dir = tmp_path / "artifacts"
    review_path = tmp_path / "phase3_reviews.csv"
    review_path.write_text(
        "\n".join(
            [
                "event_review_id,ticker,issuer_name,candidate_event_date,original_assigned_event_date,review_status,corrected_event_date,reviewer_note,reviewed_at,reviewer_id",
                "AAPL|specific_purchase|2024-06-30,AAPL,Apple Inc.,2024-06-30,2024-06-30,accepted,,Historical execution wording,2026-08-17T12:00:00Z,tester",
            ]
        ),
        encoding="utf-8",
    )
    config_path = _write_phase3_config(tmp_path, universe_path, price_path, fixture_dir, review_path, output_dir)

    output_dir.mkdir()
    reports_dir = output_dir / "reports"
    reports_dir.mkdir()
    stale_paths = [
        output_dir / "candidate_review_packet.csv",
        output_dir / "review_decisions.csv",
        output_dir / "review_decisions_reviewer_a.csv",
        output_dir / "review_decisions_reviewer_b.csv",
        output_dir / "review_consensus_audit.csv",
        output_dir / "review_consensus_decisions.csv",
        reports_dir / "candidate_review_packet.md",
        reports_dir / "review_consensus_summary.md",
        reports_dir / "review_workflow_instructions.md",
    ]
    for stale_path in stale_paths:
        stale_path.write_text("stale", encoding="utf-8")

    import src.pipeline.run_batch as run_batch_module

    monkeypatch.setattr(run_batch_module, "write_phase3_candidate_quality_reports", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        run_batch_module,
        "write_phase2_summary_reports",
        lambda output_dir, *args, **kwargs: output_dir / "reports" / "phase2_research_summary.md",
    )

    def _fake_process_phase3_company(company, config, loader, benchmark_prices, reviews):
        ticker = str(company["ticker"])
        return run_batch_module.CompanyRunArtifacts(
            status=CompanyProcessingStatus(
                ticker=ticker,
                company_name=str(company["company_name"]),
                cik=str(company["cik"]),
                sector=str(company["gics_sector"]),
                sub_industry=str(company["gics_sub_industry"]),
                issuer_id=str(company["issuer_id"]),
                primary_ticker=str(company["primary_ticker"]),
                is_primary_share_class=bool(company["is_primary_share_class"]),
                processing_status="completed",
                candidate_events_found=1,
                accepted_events=1,
                usable_event_windows=1,
                processing_timestamp="2026-08-17T12:00:00+00:00",
            ),
            audit_frame=pd.DataFrame([{"ticker": ticker, "event_review_id": "AAPL|specific_purchase|2024-06-30"}]),
            panel_frame=pd.DataFrame([{"ticker": ticker, "event_id": 1, "event_date": "2024-06-30", "tau": 0}]),
            review_queue_frame=pd.DataFrame(
                [
                    {
                        "ticker": ticker,
                        "event_review_id": "AAPL|specific_purchase|2024-06-30",
                        "candidate_event_date": "2024-06-30",
                        "review_priority_tier": "Tier1",
                        "quality_category": "plausible_specific_purchase_date",
                    }
                ]
            ),
        )

    monkeypatch.setattr(run_batch_module, "_process_phase3_company", _fake_process_phase3_company)

    run_phase2_batch(config_path)

    for stale_path in stale_paths:
        assert not stale_path.exists()
    assert (output_dir / "applied_review_decisions.csv").exists()


def test_run_phase2_batch_phase3_auto_policy_review_skips_ticker_price_loads_when_event_study_disabled(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    (fixture_dir / "aapl.yaml").write_text(
        "\n".join(
            [
                "ticker: AAPL",
                "filing_type: DEF 14A",
                'filing_date: "2024-10-24"',
                "source_id: aapl_exec_fixture",
                "text: |",
                "  Includes 67,795,754 shares remaining available for issuance as of June 30, 2024 under the Employee Stock Purchase Plan, after the exercise of purchase rights on that date.",
            ]
        ),
        encoding="utf-8",
    )
    price_path = tmp_path / "spy_only_prices.csv"
    price_path.write_text(
        "\n".join(
            [
                "ticker,date,open,high,low,close,volume",
                "SPY,2024-06-28,300,301,299,300,1500000",
                "SPY,2024-06-30,302,303,301,302,1500000",
                "SPY,2024-07-01,303,304,302,303,1500000",
            ]
        ),
        encoding="utf-8",
    )
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "\n".join(
            [
                "ticker,company_name,issuer_name,issuer_id,cik,gics_sector,gics_sub_industry,primary_ticker,is_primary_share_class",
                "AAPL,Apple Inc.,Apple Inc.,apple-inc,320193,Information Technology,Technology Hardware Storage & Peripherals,AAPL,true",
            ]
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "artifacts"
    config_path = _write_phase3_config(
        tmp_path=tmp_path,
        universe_path=universe_path,
        price_path=price_path,
        fixture_dir=fixture_dir,
        review_path=None,
        output_dir=output_dir,
        event_study_enabled=False,
        auto_policy_review=True,
        review_as_of_date="2026-08-17",
    )

    run_phase2_batch(config_path)

    status = pd.read_csv(output_dir / STATUS_FILE_NAME)
    audit = pd.read_csv(output_dir / "espp_date_audit.csv")

    assert status.loc[0, "processing_status"] == "completed"
    assert status.loc[0, "accepted_events"] == 1
    assert audit.loc[0, "review_status"] == "accepted"
    assert audit.loc[0, "reviewer_id"] == "policy_auto_review"
    assert not (output_dir / "all_event_windows.csv").exists()


def test_run_phase2_batch_persists_completed_issuer_state_before_interruption(tmp_path: Path, monkeypatch) -> None:
    fixture_dir = _write_fixture_dir(tmp_path)
    price_path = _write_price_file(tmp_path)
    universe_path = _write_universe_file(tmp_path)
    review_path = _write_review_file(tmp_path)
    output_dir = tmp_path / "artifacts"
    config_path = _write_config(tmp_path, universe_path, price_path, fixture_dir, review_path, output_dir)

    import src.pipeline.run_batch as run_batch_module

    calls: list[str] = []

    def _fake_process_primary_company(company, config, loader, benchmark_prices, reviews):
        ticker = str(company["ticker"])
        calls.append(ticker)
        if ticker == "CRM":
            raise KeyboardInterrupt("stop after first issuer")
        return run_batch_module.CompanyRunArtifacts(
            status=CompanyProcessingStatus(
                ticker=ticker,
                company_name=str(company["company_name"]),
                cik=str(company["cik"]),
                sector=str(company["gics_sector"]),
                sub_industry=str(company["gics_sub_industry"]),
                issuer_id=str(company["issuer_id"]),
                primary_ticker=str(company["primary_ticker"]),
                is_primary_share_class=bool(company["is_primary_share_class"]),
                processing_status="completed",
                accepted_events=1,
                usable_event_windows=1,
                processing_timestamp="2026-08-17T12:00:00+00:00",
            ),
            audit_frame=pd.DataFrame([{"ticker": ticker, "assigned_event_date": "2024-06-30"}]),
            panel_frame=pd.DataFrame([{"ticker": ticker, "event_id": 1, "event_date": "2024-06-30", "tau": 0}]),
        )

    monkeypatch.setattr(run_batch_module, "_process_primary_company", _fake_process_primary_company)

    with pytest.raises(KeyboardInterrupt, match="stop after first issuer"):
        run_phase2_batch(config_path)

    status = pd.read_csv(output_dir / STATUS_FILE_NAME)

    assert calls == ["AAPL", "CRM"]
    assert status["ticker"].tolist() == ["AAPL"]
    assert status.loc[0, "processing_status"] == "completed"
