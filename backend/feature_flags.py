"""Small, environment-backed kill switches for controlled beta rollout."""
from __future__ import annotations

import os


FALSE_VALUES = {"0", "false", "off", "no"}


def enabled(name: str, *, default: bool = True) -> bool:
    fallback = "1" if default else "0"
    return os.getenv(name, fallback).strip().lower() not in FALSE_VALUES


def prediction_market_enrichment_enabled() -> bool:
    return enabled("PREDICTION_MARKET_ENRICHMENT_ENABLED")


def conversational_dashboards_enabled() -> bool:
    return enabled("CONVERSATIONAL_DASHBOARDS_ENABLED")
