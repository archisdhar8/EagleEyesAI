from __future__ import annotations

import calendar
import math
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Iterable

from . import database


MODEL_VERSION = "macro-regime-rules-v1"
REGIME_KEYS = (
    "soft_landing",
    "sticky_inflation",
    "recession_cuts",
    "growth_reacceleration",
    "oil_shock",
)
REGIME_SERIES = (
    "CPIAUCSL",
    "UNRATE",
    "T10Y2Y",
    "BAMLH0A0HYM2",
    "FEDFUNDS",
    "DCOILWTICO",
    "INDPRO",
    "PAYEMS",
)


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _clip(value: float, low: float = -2.0, high: float = 2.0) -> float:
    return max(low, min(high, value))


def month_ends(start: date, end: date) -> list[date]:
    cursor = date(start.year, start.month, 1)
    values: list[date] = []
    while cursor <= end:
        last = date(cursor.year, cursor.month, calendar.monthrange(cursor.year, cursor.month)[1])
        if last >= start and last <= end:
            values.append(last)
        cursor = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)
    return values


def point_in_time_series(
    observations: Iterable[dict[str, Any]], as_of: date
) -> dict[str, list[tuple[date, float, date]]]:
    latest: dict[tuple[str, date], tuple[date, float]] = {}
    for row in observations:
        observation_date = _date(row["observation_date"])
        vintage_date = _date(row["vintage_date"])
        if observation_date > as_of or vintage_date > as_of or row.get("value") is None:
            continue
        key = (str(row["series_id"]), observation_date)
        if key not in latest or vintage_date > latest[key][0]:
            latest[key] = (vintage_date, float(row["value"]))
    grouped: dict[str, list[tuple[date, float, date]]] = defaultdict(list)
    for (series_id, observation_date), (vintage_date, value) in latest.items():
        grouped[series_id].append((observation_date, value, vintage_date))
    for values in grouped.values():
        values.sort(key=lambda item: item[0])
    return dict(grouped)


def _change(values: list[tuple[date, float, date]], periods: int, percent: bool = False) -> float | None:
    if len(values) <= periods:
        return None
    current, prior = values[-1][1], values[-1 - periods][1]
    if percent:
        return None if prior == 0 else current / prior - 1
    return current - prior


def _softmax(scores: dict[str, float], temperature: float = 1.25) -> dict[str, float]:
    peak = max(scores.values())
    values = {key: math.exp((value - peak) / temperature) for key, value in scores.items()}
    total = sum(values.values()) or 1.0
    return {key: round(value / total, 6) for key, value in values.items()}


def build_regime_label(as_of: date, observations: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    series = point_in_time_series(observations, as_of)
    available = {key for key in REGIME_SERIES if series.get(key)}
    if len(available) < 5:
        return None

    latest = {key: values[-1][1] for key, values in series.items() if values}
    inflation_yoy = _change(series.get("CPIAUCSL", []), 12, percent=True)
    unemployment = latest.get("UNRATE")
    unemployment_change = _change(series.get("UNRATE", []), 3)
    yield_curve = latest.get("T10Y2Y")
    credit_spread = latest.get("BAMLH0A0HYM2")
    policy_rate_change = _change(series.get("FEDFUNDS", []), 3)
    oil_change = _change(series.get("DCOILWTICO", []), 3, percent=True)
    industrial_growth = _change(series.get("INDPRO", []), 12, percent=True)
    payroll_growth = _change(series.get("PAYEMS", []), 12, percent=True)

    inflation_pressure = _clip(((inflation_yoy or 0.025) - 0.025) / 0.0125)
    unemployment_stress = _clip(((unemployment or 4.5) - 4.5) / 1.0)
    unemployment_momentum = _clip((unemployment_change or 0.0) / 0.5)
    curve_inversion = _clip(-(yield_curve or 0.0) / 0.75)
    credit_stress = _clip(((credit_spread or 4.5) - 4.5) / 1.5)
    rate_cuts = _clip(-(policy_rate_change or 0.0) / 0.75)
    oil_pressure = _clip((oil_change or 0.0) / 0.20)
    industrial_momentum = _clip((industrial_growth or 0.0) / 0.04)
    payroll_momentum = _clip((payroll_growth or 0.0) / 0.025)

    scores = {
        "soft_landing": (
            0.55 - abs(inflation_pressure) * 0.35 - max(unemployment_stress, 0) * 0.45
            - max(credit_stress, 0) * 0.35 + max(industrial_momentum, 0) * 0.25
            + max(payroll_momentum, 0) * 0.20
        ),
        "sticky_inflation": (
            inflation_pressure * 1.05 + max(oil_pressure, 0) * 0.35
            + max(-rate_cuts, 0) * 0.20 - max(unemployment_stress, 0) * 0.15
        ),
        "recession_cuts": (
            unemployment_stress * 0.65 + unemployment_momentum * 0.55
            + credit_stress * 0.65 + curve_inversion * 0.30 + rate_cuts * 0.35
            - industrial_momentum * 0.50 - payroll_momentum * 0.35
        ),
        "growth_reacceleration": (
            industrial_momentum * 0.65 + payroll_momentum * 0.45
            - max(credit_stress, 0) * 0.40 - max(unemployment_stress, 0) * 0.25
            - max(inflation_pressure, 0) * 0.20 - max(curve_inversion, 0) * 0.15
        ),
        "oil_shock": oil_pressure * 1.20 + max(inflation_pressure, 0) * 0.30,
    }
    probabilities = _softmax(scores)
    ordered = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
    data_quality = len(available) / len(REGIME_SERIES)
    confidence = max(0.05, min(1.0, ordered[0][1] * (0.55 + 0.45 * data_quality)))
    latest_dates = {
        key: values[-1][0].isoformat() for key, values in series.items() if values and key in REGIME_SERIES
    }
    latest_vintages = {
        key: values[-1][2].isoformat() for key, values in series.items() if values and key in REGIME_SERIES
    }
    return {
        "as_of_date": as_of.isoformat(), "model_version": MODEL_VERSION,
        "dominant_regime": ordered[0][0], "probabilities": probabilities,
        "confidence": round(confidence, 6), "data_quality": round(data_quality, 6),
        "is_point_in_time": True,
        "inputs": {
            "inflation_yoy": inflation_yoy, "unemployment": unemployment,
            "unemployment_change_3m": unemployment_change, "yield_curve": yield_curve,
            "credit_spread": credit_spread, "policy_rate_change_3m": policy_rate_change,
            "oil_change_3m": oil_change, "industrial_growth_yoy": industrial_growth,
            "payroll_growth_yoy": payroll_growth, "latest_observation_dates": latest_dates,
            "latest_vintage_dates": latest_vintages, "vintage_cutoff": as_of.isoformat(),
            "series_available": sorted(available),
        },
    }


def generate_and_store_regimes(start: date = date(2006, 1, 31), end: date | None = None) -> int:
    end = end or datetime.now(timezone.utc).date()
    history_start = date(start.year - 2, 1, 1)
    with database.postgres_connection() as conn:
        rows = conn.execute(
            """SELECT series_id, observation_date, vintage_date, value
            FROM public.macro_observations
            WHERE series_id = ANY(%s) AND is_point_in_time=true
              AND vintage_date <= %s AND observation_date >= %s
            ORDER BY vintage_date, observation_date""",
            (list(REGIME_SERIES), end, history_start),
        ).fetchall()
    labels = [
        label for as_of in month_ends(start, end)
        if (label := build_regime_label(as_of, rows)) is not None
    ]
    if not labels:
        return 0
    with database.postgres_connection() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO public.macro_regime_labels(
                as_of_date, model_version, dominant_regime, probabilities, inputs,
                confidence, data_quality, is_point_in_time
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,true)
                ON CONFLICT (as_of_date, model_version) DO UPDATE SET
                dominant_regime=excluded.dominant_regime,
                probabilities=excluded.probabilities, inputs=excluded.inputs,
                confidence=excluded.confidence, data_quality=excluded.data_quality,
                is_point_in_time=true""",
                [
                    (
                        label["as_of_date"], label["model_version"], label["dominant_regime"],
                        database._jsonb(label["probabilities"]), database._jsonb(label["inputs"]),
                        label["confidence"], label["data_quality"],
                    )
                    for label in labels
                ],
            )
    return len(labels)
