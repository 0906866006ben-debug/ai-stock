from backend.app.services.data_sources.tpex_client import normalize_tpex_mainboard_quote


def test_tpex_mainboard_quote_normalize() -> None:
    row = {
        "Date": "1150514",
        "SecuritiesCompanyCode": "8069",
        "CompanyName": "元太",
        "Open": "217.00",
        "High": "231.00",
        "Low": "208.50",
        "Close": "226.00",
        "TradingShares": "51,749,320",
        "TransactionAmount": "11,444,463,469",
    }

    normalized = normalize_tpex_mainboard_quote(row)

    assert normalized is not None
    assert normalized["stock_id"] == "8069"
    assert normalized["stock_name"] == "元太"
    assert normalized["date"] == "2026-05-14"
    assert normalized["open"] == 217.0
    assert normalized["high"] == 231.0
    assert normalized["low"] == 208.5
    assert normalized["close"] == 226.0
    assert normalized["volume"] == 51_749_320
    assert normalized["turnover_value"] == 11_444_463_469
    assert normalized["source"] == "tpex_official"
    assert normalized["turnover_source"] == "official"
    assert normalized["is_official"] is True

