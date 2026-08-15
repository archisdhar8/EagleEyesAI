from __future__ import annotations

import csv
import io
import re
from collections import OrderedDict
from typing import Any

from .models import Holding, PortfolioPayload


FIELD_ALIASES = {
    "ticker": {"ticker", "symbol", "security", "stock", "instrument", "code"},
    "shares": {"shares", "share", "quantity", "qty", "units", "positionquantity"},
    "weight": {"weight", "allocation", "portfolioallocation", "portfolio_weight", "targetweight"},
    "weight_percent": {"weightpercent", "allocationpercent", "weightpct", "allocationpct", "percentofaccount", "portfolio_percent"},
    "market_value": {"marketvalue", "currentvalue", "positionvalue", "value", "market_value"},
    "price": {"price", "lastprice", "currentprice", "marketprice"},
    "cost_basis": {"costbasis", "totalcost", "bookvalue", "cost", "cost_basis"},
    "account_type": {"accounttype", "account", "accountname", "registration", "account_type"},
    "acquisition_date": {"acquisitiondate", "purchasedate", "acquired", "dateacquired", "acquisition_date"},
}


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.strip().lower())


def _number(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"n/a", "na", "none", "--", "-"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[$,%\s]", "", text.strip("()"))
    parsed = float(cleaned)
    return -parsed if negative else parsed


def _account(value: Any) -> str:
    text = _key(str(value or "taxable"))
    if "roth" in text:
        return "roth_ira"
    if "401" in text or "employer" in text:
        return "401k"
    if "ira" in text or "traditional" in text or "rollover" in text:
        return "traditional_ira"
    if text in {"taxable", "brokerage", "individual", "joint", "trust"}:
        return "taxable"
    return "other"


def _dialect(text: str) -> csv.Dialect:
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def parse_portfolio_csv(csv_text: str, name: str = "Imported portfolio") -> dict[str, Any]:
    text = csv_text.strip().lstrip("\ufeff")
    if not text:
        raise ValueError("Portfolio file is empty")
    reader = csv.DictReader(io.StringIO(text), dialect=_dialect(text))
    if not reader.fieldnames:
        raise ValueError("Portfolio file needs a header row")

    normalized_headers = {_key(header): header for header in reader.fieldnames if header}
    detected: dict[str, str] = {}
    for canonical, aliases in FIELD_ALIASES.items():
        match = next((normalized_headers[alias] for alias in aliases if alias in normalized_headers), None)
        if match:
            detected[canonical] = match
    if "ticker" not in detected:
        raise ValueError("Could not find a security identifier column. Use ticker, symbol, security, stock, instrument, or code.")

    warnings: list[str] = []
    if "weight" in detected and "weight_percent" in detected:
        warnings.append("Both decimal and percentage weight columns were found; the explicit percentage column was used.")
    used_headers = set(detected.values())
    ignored = [header for header in reader.fieldnames if header not in used_headers]
    if ignored:
        warnings.append(f"Ignored {len(ignored)} unrelated column(s): {', '.join(ignored[:8])}{'…' if len(ignored) > 8 else ''}")

    parsed_rows: list[dict[str, Any]] = []
    inferred_percent = False
    for line_number, row in enumerate(reader, start=2):
        ticker = str(row.get(detected["ticker"], "") or "").strip().upper()
        if not ticker or ticker in {"TOTAL", "SUBTOTAL", "CASH TOTAL", "ACCOUNT TOTAL"}:
            continue
        values: dict[str, Any] = {"ticker": ticker, "account_type": _account(row.get(detected.get("account_type", "")))}
        for field in ("shares", "market_value", "cost_basis"):
            if field in detected:
                value = _number(row.get(detected[field]))
                if value is not None:
                    values[field] = max(0.0, value)
        price = _number(row.get(detected.get("price", ""))) if "price" in detected else None
        if values.get("market_value") is None and values.get("shares") is not None and price is not None:
            values["market_value"] = max(0.0, values["shares"] * price)
        weight_field = "weight_percent" if "weight_percent" in detected else "weight" if "weight" in detected else None
        if weight_field:
            raw = row.get(detected[weight_field])
            weight = _number(raw)
            if weight is not None:
                if weight_field == "weight_percent" or "%" in str(raw) or weight > 1:
                    if weight_field == "weight" and "%" not in str(raw):
                        inferred_percent = True
                    weight /= 100
                values["weight"] = weight
        if "acquisition_date" in detected and row.get(detected["acquisition_date"]):
            values["acquisition_date"] = str(row[detected["acquisition_date"]]).strip()
        parsed_rows.append(values)
    if not parsed_rows:
        raise ValueError("No security rows were found")
    if inferred_percent:
        warnings.append("Weight values above 1 were interpreted as percentages.")

    grouped: OrderedDict[str, dict[str, Any]] = OrderedDict()
    duplicate_count = 0
    for row in parsed_rows:
        ticker = row["ticker"]
        if ticker not in grouped:
            grouped[ticker] = row
            continue
        duplicate_count += 1
        current = grouped[ticker]
        for field in ("shares", "weight", "market_value", "cost_basis"):
            if row.get(field) is not None:
                current[field] = float(current.get(field) or 0) + float(row[field])
        if current.get("account_type") != row.get("account_type"):
            current["account_type"] = "other"
        dates = [value for value in (current.get("acquisition_date"), row.get("acquisition_date")) if value]
        if dates:
            current["acquisition_date"] = min(dates)
    if duplicate_count:
        warnings.append(f"Combined {duplicate_count} duplicate ticker row(s); positions spanning multiple accounts are marked Other.")

    holdings = list(grouped.values())
    market_total = sum(float(row.get("market_value") or 0) for row in holdings)
    if market_total > 0:
        for row in holdings:
            if row.get("weight") is None and row.get("market_value") is not None:
                row["weight"] = float(row["market_value"]) / market_total
    missing_size = [row for row in holdings if all(row.get(field) is None for field in ("shares", "weight", "market_value"))]
    if missing_size:
        equal_weight = 1 / len(holdings)
        for row in missing_size:
            row["weight"] = equal_weight
        warnings.append(f"Assigned equal placeholder weights to {len(missing_size)} row(s) without quantity, value, or allocation. Review before saving.")

    validated = [Holding.model_validate(row).model_dump(mode="json") for row in holdings]
    PortfolioPayload(name=name, holdings=[Holding.model_validate(row) for row in validated])
    return {
        "holdings": validated,
        "warnings": warnings,
        "detected_columns": detected,
        "ignored_columns": ignored,
        "source_rows": len(parsed_rows),
    }
