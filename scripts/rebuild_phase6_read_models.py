#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import database, phase6_domains  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize Phase 6 fast domain read models outside Ask.")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--ticker", action="append", default=[])
    parser.add_argument("--portfolio-id")
    parser.add_argument("--domains", default="company,macro,market,prediction",
                        help="Comma-separated company,macro,market,prediction")
    args = parser.parse_args()
    database.initialize()
    selected = {value.strip().lower() for value in args.domains.split(",") if value.strip()}
    output: dict[str, object] = {}
    if "company" in selected:
        output["company"] = [phase6_domains.materialize_company(args.user_id, ticker).model_dump(mode="json")
                             for ticker in args.ticker]
    if "macro" in selected:
        output["macro"] = phase6_domains.materialize_macro(args.user_id).model_dump(mode="json")
    if "market" in selected:
        output["market"] = phase6_domains.materialize_market(args.user_id).model_dump(mode="json")
    if "prediction" in selected:
        output["prediction"] = phase6_domains.materialize_prediction_markets(
            args.user_id, portfolio_id=args.portfolio_id,
        ).model_dump(mode="json")
    print(json.dumps(output, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
