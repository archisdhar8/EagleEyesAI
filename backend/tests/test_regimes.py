from datetime import date

import pytest
import requests

from backend.ingestion import (
    parse_alfred_observations,
    parse_non_revised_monthly_proxy,
    request_with_retries,
)
from backend.regimes import REGIME_KEYS, build_regime_label, month_ends, point_in_time_series


def test_month_ends_are_bounded() -> None:
    assert month_ends(date(2024, 1, 15), date(2024, 3, 31)) == [
        date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31)
    ]


def test_point_in_time_series_excludes_future_revisions() -> None:
    rows = [
        {"series_id": "CPIAUCSL", "observation_date": "2024-01-01", "vintage_date": "2024-01-15", "value": 100},
        {"series_id": "CPIAUCSL", "observation_date": "2024-01-01", "vintage_date": "2024-02-15", "value": 200},
        {"series_id": "CPIAUCSL", "observation_date": "2024-02-01", "vintage_date": "2024-02-15", "value": 300},
    ]
    result = point_in_time_series(rows, date(2024, 1, 31))
    assert result["CPIAUCSL"] == [(date(2024, 1, 1), 100.0, date(2024, 1, 15))]


def test_regime_probabilities_use_only_available_inputs() -> None:
    rows = []
    series_values = {
        "CPIAUCSL": [300 + index * 0.8 for index in range(13)],
        "UNRATE": [4.0 + index * 0.02 for index in range(13)],
        "T10Y2Y": [-0.5 + index * 0.03 for index in range(13)],
        "BAMLH0A0HYM2": [3.8 + index * 0.02 for index in range(13)],
        "FEDFUNDS": [5.25 - index * 0.05 for index in range(13)],
        "DCOILWTICO": [70 + index for index in range(13)],
        "INDPRO": [100 + index * 0.2 for index in range(13)],
        "PAYEMS": [155000 + index * 180 for index in range(13)],
    }
    for series_id, values in series_values.items():
        for index, value in enumerate(values):
            year = 2024 + index // 12
            month = index % 12 + 1
            rows.append(
                {
                    "series_id": series_id, "observation_date": date(year, month, 1),
                    "vintage_date": date(year, month, 20), "value": value,
                }
            )
    label = build_regime_label(date(2025, 1, 31), rows)
    assert label is not None
    assert set(label["probabilities"]) == set(REGIME_KEYS)
    assert sum(label["probabilities"].values()) == pytest.approx(1, abs=1e-5)
    assert label["inputs"]["vintage_cutoff"] == "2025-01-31"
    assert all(value <= "2025-01-31" for value in label["inputs"]["latest_vintage_dates"].values())


def test_alfred_parser_maps_vintage_columns_and_lookback() -> None:
    vintage = date(2024, 3, 31)
    rows = [
        {"date": "2024-02-01", "UNRATE_20240331": "3.9"},
        {"date": "2024-04-01", "UNRATE_20240331": "4.0"},
        {"date": "2020-01-01", "UNRATE_20240331": "3.5"},
        {"date": "2024-03-01", "UNRATE_20240331": "."},
    ]
    parsed = parse_alfred_observations("UNRATE", [vintage], rows, "eop")
    assert len(parsed) == 1
    assert parsed[0][1:5] == ("UNRATE", date(2024, 2, 1), vintage, 3.9)


def test_non_revised_proxy_aggregates_without_future_months() -> None:
    rows = [
        {"date": "2024-01-02", "value": "70"},
        {"date": "2024-01-31", "value": "74"},
        {"date": "2024-02-01", "value": "80"},
    ]
    parsed = parse_non_revised_monthly_proxy("DCOILWTICO", rows, "avg", date(2024, 1, 31))
    assert len(parsed) == 1
    assert parsed[0][0:5] == (
        "FRED_PIT_PROXY", "DCOILWTICO", date(2024, 1, 1), date(2024, 1, 31), 72.0
    )


def test_provider_network_errors_do_not_echo_request_credentials() -> None:
    class BrokenSession:
        def get(self, *_args, **_kwargs):
            raise requests.ConnectionError("failed URL ?api_key=should-never-appear")

    with pytest.raises(RuntimeError) as error:
        request_with_retries(
            BrokenSession(), "https://provider.invalid", params={"api_key": "secret"}, attempts=1
        )
    assert "secret" not in str(error.value)
    assert "should-never-appear" not in str(error.value)
