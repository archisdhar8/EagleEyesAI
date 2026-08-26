from collections import Counter

from backend.research_metric_registry import REGISTRY
from backend.research_provider_capability_registry import CAPABILITIES, CAPABILITY_BY_KEY, capability_payload


def test_provider_capability_registry_is_complete_and_exclusive() -> None:
    allowed = {
        "AVAILABLE_STORED", "AVAILABLE_POLYGON_NOT_INGESTED", "AVAILABLE_SEC_NOT_EXTRACTED",
        "DERIVABLE_FROM_EXISTING_DATA", "PLAN_GATED", "TRUE_EXTERNAL_PROVIDER_GAP", "MODEL_OUTPUT",
    }
    assert len(CAPABILITIES) == len(REGISTRY) == len(CAPABILITY_BY_KEY)
    assert set(CAPABILITY_BY_KEY) == {item.key for item in REGISTRY}
    assert set(item.classification for item in CAPABILITIES) == allowed
    assert all(item.basis and item.endpoint_or_source and item.entitlement_evidence for item in CAPABILITIES)
    assert sum(Counter(item.classification for item in CAPABILITIES).values()) == len(REGISTRY)
    assert capability_payload()["version"] == "research-provider-capability-audit-v2"
