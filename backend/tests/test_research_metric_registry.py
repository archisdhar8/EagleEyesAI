from backend.research_metric_registry import REGISTRY, SECTION_STATUS_POLICY, registry_payload


def test_registry_is_unique_complete_and_machine_readable() -> None:
    keys = [item.key for item in REGISTRY]
    assert len(REGISTRY) >= 100
    assert len(keys) == len(set(keys))
    assert {item.classification for item in REGISTRY} == {"SOURCE", "DERIVED", "MODEL", "UNAVAILABLE"}
    assert {item.section for item in REGISTRY} == {
        "header", "summary", "overview", "financial_health", "valuation", "earnings", "thesis",
        "catalysts_risks", "market_data", "ownership_sentiment", "portfolio_fit", "decision", "sources",
    }
    for item in REGISTRY:
        assert item.label
        assert item.formula
        assert item.freshness_policy
        assert item.null_behavior
        assert item.evidence_type
        assert item.status_role in {"CORE", "SUPPORTING", "INFORMATIONAL", "CONDITIONAL"}

    payload = registry_payload()
    assert payload["version"] == "research-metric-registry-v1"
    assert payload["section_status_policy"] == SECTION_STATUS_POLICY
    assert len(payload["metrics"]) == len(REGISTRY)
