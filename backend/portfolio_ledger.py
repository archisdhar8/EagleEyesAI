from __future__ import annotations

import csv
import io
import math
from collections import defaultdict
from datetime import date, datetime
from typing import Any


ALIASES = {
    "date": {"date", "trade date", "transaction date", "activity date"},
    "type": {"type", "action", "transaction type", "activity type"},
    "ticker": {"ticker", "symbol", "security", "instrument"},
    "quantity": {"quantity", "qty", "shares", "units"},
    "price": {"price", "unit price", "share price"},
    "amount": {"amount", "net amount", "value", "total"},
    "fee": {"fee", "fees", "commission"},
    "external_id": {"id", "transaction id", "activity id", "reference"},
}

TYPE_ALIASES = {
    "buy": "buy", "bought": "buy", "purchase": "buy",
    "sell": "sell", "sold": "sell",
    "deposit": "deposit", "contribution": "deposit", "cash deposit": "deposit",
    "withdrawal": "withdrawal", "distribution": "withdrawal", "cash withdrawal": "withdrawal",
    "dividend": "dividend", "div": "dividend", "interest": "income",
    "fee": "fee", "commission": "fee",
    "split": "split", "stock split": "split",
    "transfer in": "transfer_in", "transfer-in": "transfer_in",
    "transfer out": "transfer_out", "transfer-out": "transfer_out",
}


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def _date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    for fmt in (None, "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00")) if fmt is None else datetime.strptime(raw, fmt)
            return parsed.date().isoformat()
        except ValueError:
            continue
    return None


def parse_transaction_csv(csv_text: str, account_id: str) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    headers = reader.fieldnames or []
    mapped: dict[str, str] = {}
    for header in headers:
        normalized = header.strip().lower()
        canonical = next((key for key, aliases in ALIASES.items() if normalized in aliases), None)
        if canonical and canonical not in mapped:
            mapped[canonical] = header
    missing = [field for field in ("date", "type") if field not in mapped]
    if missing:
        return {"valid": False, "rows": [], "errors": [f"Missing required column: {field}" for field in missing], "column_map": mapped, "unknown_columns": [h for h in headers if h not in mapped.values()]}
    rows, errors, seen = [], [], set()
    for index, raw in enumerate(reader, start=2):
        transaction_type = TYPE_ALIASES.get(str(raw.get(mapped["type"], "")).strip().lower())
        trade_date = _date(raw.get(mapped["date"]))
        ticker = str(raw.get(mapped.get("ticker", ""), "")).strip().upper() or None
        quantity = _number(raw.get(mapped.get("quantity", "")))
        price = _number(raw.get(mapped.get("price", "")))
        amount = _number(raw.get(mapped.get("amount", "")))
        fee = abs(_number(raw.get(mapped.get("fee", ""))) or 0)
        external_id = str(raw.get(mapped.get("external_id", ""), "")).strip() or None
        if not transaction_type:
            errors.append(f"Row {index}: unsupported transaction type")
            continue
        if not trade_date:
            errors.append(f"Row {index}: invalid date")
            continue
        if transaction_type in {"buy", "sell", "dividend", "split"} and not ticker:
            errors.append(f"Row {index}: ticker is required for {transaction_type}")
            continue
        if transaction_type in {"buy", "sell"} and not quantity:
            errors.append(f"Row {index}: quantity is required for {transaction_type}")
            continue
        fingerprint = external_id or f"{trade_date}|{transaction_type}|{ticker}|{quantity}|{price}|{amount}|{fee}"
        if fingerprint in seen:
            errors.append(f"Row {index}: duplicate transaction")
            continue
        seen.add(fingerprint)
        rows.append({
            "account_id": account_id, "external_id": external_id, "trade_date": trade_date,
            "transaction_type": transaction_type, "ticker": ticker,
            "quantity": abs(quantity) if quantity is not None else None,
            "price": price, "amount": amount, "fee": fee, "currency": "USD",
            "source_row": index,
        })
    return {"valid": not errors, "rows": rows, "errors": errors, "column_map": mapped, "unknown_columns": [h for h in headers if h not in mapped.values()]}


def reconstruct_positions(transactions: list[dict[str, Any]]) -> dict[str, Any]:
    quantities: dict[str, float] = defaultdict(float)
    cash = 0.0
    warnings = []
    for row in sorted(transactions, key=lambda item: (item["trade_date"], item.get("source_row", 0))):
        kind, ticker = row["transaction_type"], row.get("ticker")
        quantity, price = float(row.get("quantity") or 0), float(row.get("price") or 0)
        amount, fee = row.get("amount"), float(row.get("fee") or 0)
        gross = float(amount) if amount is not None else quantity * price
        if kind == "buy": quantities[ticker] += quantity; cash -= gross + fee
        elif kind == "sell": quantities[ticker] -= quantity; cash += gross - fee
        elif kind in {"deposit", "transfer_in", "dividend", "income"}: cash += abs(gross) - fee
        elif kind in {"withdrawal", "transfer_out", "fee"}: cash -= abs(gross) + fee
        elif kind == "split":
            if quantity <= 0: warnings.append(f"Invalid split ratio for {ticker}")
            else: quantities[ticker] *= quantity
        if ticker and quantities[ticker] < -1e-8:
            warnings.append(f"Negative reconstructed position for {ticker} after {row['trade_date']}")
    return {"positions": {key: round(value, 8) for key, value in quantities.items() if abs(value) > 1e-8}, "cash": round(cash, 2), "warnings": warnings}


def calculate_performance(transactions: list[dict[str, Any]], valuations: list[dict[str, Any]]) -> dict[str, Any]:
    points = sorted(({"date": _date(row.get("date")), "value": float(row.get("value") or 0)} for row in valuations), key=lambda row: row["date"] or "")
    if len(points) < 2 or any(not row["date"] for row in points):
        return {"status": "unavailable", "reason": "At least two dated reconciled account valuations are required."}
    external = {"deposit", "transfer_in", "withdrawal", "transfer_out"}
    twr_factor = 1.0
    for previous, current in zip(points, points[1:]):
        flow = 0.0
        for row in transactions:
            if previous["date"] < row["trade_date"] <= current["date"] and row["transaction_type"] in external:
                amount = abs(float(row.get("amount") or 0))
                flow += amount if row["transaction_type"] in {"deposit", "transfer_in"} else -amount
        if previous["value"] > 0:
            twr_factor *= 1 + (current["value"] - flow - previous["value"]) / previous["value"]
    cashflows = [(date.fromisoformat(points[0]["date"]), -points[0]["value"])]
    for row in transactions:
        if points[0]["date"] < row["trade_date"] <= points[-1]["date"] and row["transaction_type"] in external:
            amount = abs(float(row.get("amount") or 0))
            investor_flow = -amount if row["transaction_type"] in {"deposit", "transfer_in"} else amount
            cashflows.append((date.fromisoformat(row["trade_date"]), investor_flow))
    cashflows.append((date.fromisoformat(points[-1]["date"]), points[-1]["value"]))
    return {
        "status": "ready", "time_weighted_return": twr_factor - 1,
        "money_weighted_return": _xirr(cashflows), "period_start": points[0]["date"],
        "period_end": points[-1]["date"], "valuation_count": len(points),
        "method": "Daily/subperiod time-weighted return and dated-cash-flow XIRR.",
        "version": "account-performance-v1",
        "assumptions": ["Valuations include positions, cash, dividends, splits, and fees as imported.", "Only deposits, withdrawals, and transfers are treated as external flows."],
    }


def _xirr(cashflows: list[tuple[date, float]]) -> float | None:
    if not any(value < 0 for _, value in cashflows) or not any(value > 0 for _, value in cashflows):
        return None
    origin = min(item[0] for item in cashflows)
    def npv(rate: float) -> float:
        return sum(value / ((1 + rate) ** ((when - origin).days / 365.0)) for when, value in cashflows)
    low, high = -0.9999, 10.0
    if npv(low) * npv(high) > 0:
        return None
    for _ in range(160):
        mid = (low + high) / 2
        if npv(low) * npv(mid) <= 0: high = mid
        else: low = mid
    result = (low + high) / 2
    return result if math.isfinite(result) else None


def tax_lot_coverage(transactions: list[dict[str, Any]], jurisdiction: str | None = None) -> dict[str, Any]:
    lots = []
    for row in transactions:
        if row["transaction_type"] != "buy" or not row.get("ticker"):
            continue
        basis = (float(row.get("quantity") or 0) * float(row.get("price") or 0)) + float(row.get("fee") or 0)
        lots.append({"account_id": row.get("account_id"), "ticker": row["ticker"], "acquired_at": row["trade_date"], "quantity": row.get("quantity"), "cost_basis": basis})
    missing = []
    if not jurisdiction: missing.append("tax jurisdiction")
    if not lots: missing.append("buy transactions with quantity and price")
    return {
        "status": "complete" if not missing else "partial" if lots else "unavailable",
        "included_lots": lots, "jurisdiction": jurisdiction,
        "missing_information": missing,
        "wash_sale_coverage": "unavailable until all taxable accounts and replacement purchases are imported",
        "method": "Imported acquisition lots only; no tax-lot optimization or trade instruction.",
    }
