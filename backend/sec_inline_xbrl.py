from __future__ import annotations

"""Minimal deterministic Inline XBRL parser for Research dimensional facts."""

import math
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any


VERSION = "sec-inline-xbrl-v1.0.0"


@dataclass
class Context:
    context_id: str
    period_start: str | None = None
    period_end: str | None = None
    dimensions: dict[str, str] = field(default_factory=dict)


class InlineXbrlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.contexts: dict[str, Context] = {}
        self.units: dict[str, str] = {}
        self.facts: list[dict[str, Any]] = []
        self._context: Context | None = None
        self._member_dimension: str | None = None
        self._unit_id: str | None = None
        self._capture: str | None = None
        self._fact: dict[str, Any] | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = {key.lower(): value for key, value in attrs}
        if tag.endswith(":context") or tag == "context":
            context_id = str(values.get("id") or "")
            if context_id:
                self._context = self.contexts.setdefault(context_id, Context(context_id))
        elif self._context and (tag.endswith(":startdate") or tag.endswith(":enddate") or tag.endswith(":instant")):
            self._capture, self._text = tag.rsplit(":", 1)[-1], []
        elif self._context and (tag.endswith(":explicitmember") or tag.endswith(":typedmember")):
            self._member_dimension, self._text = str(values.get("dimension") or ""), []
        elif tag.endswith(":unit") or tag == "unit":
            self._unit_id = str(values.get("id") or "")
        elif self._unit_id and tag.endswith(":measure"):
            self._capture, self._text = "measure", []
        elif tag in {"ix:nonfraction", "ix:fraction"}:
            self._fact = {
                "name": values.get("name"), "context_id": values.get("contextref"),
                "unit_id": values.get("unitref"), "scale": values.get("scale"),
                "sign": values.get("sign"), "decimals": values.get("decimals"),
                "nil": str(values.get("xsi:nil") or "").lower() == "true",
            }
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._fact is not None or self._capture or self._member_dimension:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        local = tag.rsplit(":", 1)[-1]
        text = " ".join("".join(self._text).split())
        if self._context and local in {"startdate", "enddate", "instant"} and self._capture == local:
            if local == "startdate":
                self._context.period_start = text[:10] or None
            else:
                self._context.period_end = text[:10] or None
            self._capture, self._text = None, []
        elif self._context and local in {"explicitmember", "typedmember"} and self._member_dimension:
            self._context.dimensions[self._member_dimension] = text
            self._member_dimension, self._text = None, []
        elif local == "context":
            self._context = None
        elif self._unit_id and local == "measure" and self._capture == "measure":
            self.units[self._unit_id] = text
            self._capture, self._text = None, []
        elif local == "unit":
            self._unit_id = None
        elif self._fact is not None and local in {"nonfraction", "fraction"}:
            self._fact["raw_text"] = text
            self.facts.append(self._fact)
            self._fact, self._text = None, []


def _numeric(raw: str, *, scale: Any = None, sign: Any = None) -> float | None:
    value = raw.strip().replace(",", "").replace("$", "").replace("%", "")
    if not value or value in {"-", "—", "–"}:
        return None
    parenthetical = value.startswith("(") and value.endswith(")")
    value = value.strip("()")
    try:
        result = float(value)
    except ValueError:
        return None
    try:
        result *= 10 ** int(scale or 0)
    except (TypeError, ValueError, OverflowError):
        return None
    if sign == "-" or parenthetical:
        result *= -1
    return result if math.isfinite(result) else None


def parse_inline_xbrl(html: str) -> list[dict[str, Any]]:
    parser = InlineXbrlParser()
    parser.feed(html)
    output: list[dict[str, Any]] = []
    for raw in parser.facts:
        context = parser.contexts.get(str(raw.get("context_id") or ""))
        value = None if raw.get("nil") else _numeric(str(raw.get("raw_text") or ""), scale=raw.get("scale"), sign=raw.get("sign"))
        if not context or value is None or not context.period_end or not raw.get("name"):
            continue
        taxonomy, _, concept = str(raw["name"]).partition(":")
        if not concept:
            concept, taxonomy = taxonomy, "unknown"
        output.append({
            "taxonomy": taxonomy, "concept": concept, "context_id": context.context_id,
            "period_start": context.period_start, "period_end": context.period_end,
            "dimensions": dict(context.dimensions), "unit": parser.units.get(str(raw.get("unit_id") or "")),
            "value": value, "decimals": raw.get("decimals"), "raw_text": raw.get("raw_text"),
            "parser_version": VERSION,
        })
    return output


AXIS_PATTERN = re.compile(r"(product|service|segment|geograph|country|region|majorcustomer|customer)", re.I)
CONCEPT_PATTERN = re.compile(
    r"(revenue|sales|customer|grossProfit|operatingIncome|netIncome|profitLoss|earningsPerShare|netCashProvided|cashAndCash|longTermDebt|stockholdersEquity|assets|liabilities|depreciation|amortization|incomeTax|taxExpense|beforeIncomeTax|propertyPlant|capitalExpenditure|paymentsToAcquire|sharesOutstanding|weightedAverageNumberOfShares)",
    re.I,
)


def research_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep dimensional facts and explicitly required financial concepts."""
    return [
        fact for fact in facts
        if CONCEPT_PATTERN.search(str(fact.get("concept") or ""))
        or any(AXIS_PATTERN.search(str(axis)) for axis in (fact.get("dimensions") or {}))
    ]
