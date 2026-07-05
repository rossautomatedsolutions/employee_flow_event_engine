from pathlib import Path

import pytest

from src.universe.sp500_universe import load_sp500_universe


def test_load_sp500_universe_normalizes_tickers_ciks_and_share_class_groups(tmp_path: Path) -> None:
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "\n".join(
            [
                "ticker,company_name,issuer_name,issuer_id,cik,gics_sector,gics_sub_industry,primary_ticker,is_primary_share_class",
                "goog,Alphabet Inc. (Class C),Alphabet Inc.,alphabet-inc,1652044,Communication Services,Interactive Media & Services,GOOGL,false",
                "GOOGL,Alphabet Inc. (Class A),Alphabet Inc.,alphabet-inc,1652044,Communication Services,Interactive Media & Services,GOOGL,true",
                "BRK/B,Berkshire Hathaway,Berkshire Hathaway,berkshire-hathaway,1067983,Financials,Multi-Sector Holdings,BRK/B,true",
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_sp500_universe(universe_path)

    assert loaded.companies["ticker"].tolist() == ["BRK.B", "GOOG", "GOOGL"]
    assert loaded.companies["cik"].tolist() == ["0001067983", "0001652044", "0001652044"]
    assert loaded.companies.loc[loaded.companies["ticker"] == "GOOG", "primary_ticker"].iloc[0] == "GOOGL"
    assert bool(loaded.companies.loc[loaded.companies["ticker"] == "GOOG", "is_primary_share_class"].iloc[0]) is False
    assert len(loaded.report.legitimate_share_class_groups) == 1
    assert loaded.report.legitimate_share_class_groups[0].tickers == ("GOOG", "GOOGL")


def test_load_sp500_universe_rejects_duplicate_tickers_after_normalization(tmp_path: Path) -> None:
    universe_path = tmp_path / "bad_universe.csv"
    universe_path.write_text(
        "\n".join(
            [
                "ticker,company_name,issuer_name,issuer_id,cik,gics_sector,gics_sub_industry,primary_ticker,is_primary_share_class",
                "BRK.B,Berkshire Hathaway,Berkshire Hathaway,berkshire-hathaway,1067983,Financials,Multi-Sector Holdings,BRK.B,true",
                "BRK/B,Berkshire Hathaway Alias,Berkshire Hathaway,berkshire-hathaway,1067984,Financials,Multi-Sector Holdings,BRK/B,true",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate tickers remain after normalization"):
        load_sp500_universe(universe_path)


def test_load_sp500_universe_rejects_malformed_duplicate_cik_group(tmp_path: Path) -> None:
    universe_path = tmp_path / "bad_share_classes.csv"
    universe_path.write_text(
        "\n".join(
            [
                "ticker,company_name,issuer_name,issuer_id,cik,gics_sector,gics_sub_industry,primary_ticker,is_primary_share_class",
                "GOOG,Alphabet Inc. (Class C),Alphabet Inc.,alphabet-inc,1652044,Communication Services,Interactive Media & Services,GOOG,false",
                "GOOGL,Alphabet Inc. (Class A),Alphabet Inc.,alphabet-inc,1652044,Communication Services,Interactive Media & Services,GOOG,false",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate CIK group 0001652044 is malformed"):
        load_sp500_universe(universe_path)
