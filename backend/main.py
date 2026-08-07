from __future__ import annotations

import csv
import io
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import database
from .analysis import latest_macro, run_analysis, security_research
from .explanations import generate_explanation
from .models import AnalysisRequest, ExplanationRequest, Holding, InvestorProfile, PortfolioPayload
from .scenarios import refresh as refresh_scenarios


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    if database.load_profile() is None:
        database.save_profile(InvestorProfile().model_dump(mode="json"))
    if not database.list_portfolios():
        database.save_portfolio(
            "Starter portfolio",
            [
                {"ticker": "AAPL", "weight": 0.28, "account_type": "taxable"},
                {"ticker": "MU", "weight": 0.22, "account_type": "taxable"},
                {"ticker": "CSCO", "weight": 0.18, "account_type": "taxable"},
                {"ticker": "SPY", "weight": 0.22, "account_type": "taxable"},
                {"ticker": "CASH", "weight": 0.10, "account_type": "taxable"},
            ],
        )
    yield


app = FastAPI(title="InvestmentDashboard Local API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["*"] ,
    allow_headers=["*"] ,
)


class CsvImport(BaseModel):
    name: str = "Imported portfolio"
    csv_text: str


@app.get("/api/health")
def health() -> dict[str, Any]:
    mode = database.storage_mode()
    return {"status": "ok", "mode": mode, "storage": mode, "trading_enabled": False}


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    portfolios = database.list_portfolios()
    portfolio = portfolios[0] if portfolios else None
    profile = database.load_profile() or InvestorProfile().model_dump(mode="json")
    scenarios = refresh_scenarios(force=False)
    holdings = portfolio["holdings"] if portfolio else []
    tickers = [holding["ticker"] for holding in holdings] + profile.get("watchlist", [])
    research = security_research(tickers)
    return {"portfolio": portfolio, "profile": profile, "macro": latest_macro(), "scenarios": scenarios, "research": research, "storage": database.storage_mode()}


@app.get("/api/portfolios")
def portfolios() -> list[dict[str, Any]]:
    return database.list_portfolios()


@app.post("/api/portfolios")
def create_portfolio(payload: PortfolioPayload) -> dict[str, Any]:
    return database.save_portfolio(payload.name, [item.model_dump(mode="json") for item in payload.holdings])


@app.put("/api/portfolios/{portfolio_id}")
def update_portfolio(portfolio_id: str, payload: PortfolioPayload) -> dict[str, Any]:
    try:
        return database.save_portfolio(payload.name, [item.model_dump(mode="json") for item in payload.holdings], portfolio_id)
    except KeyError as exc:
        raise HTTPException(404, "Portfolio not found") from exc


@app.post("/api/portfolios/import")
def import_portfolio(payload: CsvImport) -> dict[str, Any]:
    try:
        reader = csv.DictReader(io.StringIO(payload.csv_text.strip()))
        if not reader.fieldnames or "ticker" not in {name.lower().strip() for name in reader.fieldnames}:
            raise ValueError("CSV requires a ticker column")
        holdings = []
        normalized_names = {name.lower().strip(): name for name in reader.fieldnames}
        for line_number, row in enumerate(reader, start=2):
            normalized = {key: row.get(original) for key, original in normalized_names.items()}
            values: dict[str, Any] = {"ticker": (normalized.get("ticker") or "").strip().upper(), "account_type": (normalized.get("account_type") or "taxable").strip().lower()}
            for key in ["shares", "weight", "market_value", "cost_basis"]:
                if normalized.get(key) not in {None, ""}:
                    values[key] = float(str(normalized[key]).replace(",", "").replace("$", ""))
            if normalized.get("acquisition_date"):
                values["acquisition_date"] = normalized["acquisition_date"]
            try:
                holdings.append(Holding.model_validate(values).model_dump(mode="json"))
            except Exception as exc:
                raise ValueError(f"Invalid row {line_number}: {exc}") from exc
        if not holdings:
            raise ValueError("CSV contains no holdings")
    except (csv.Error, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    portfolio = database.save_portfolio(payload.name, holdings)
    return {"portfolio": portfolio, "validated_rows": len(holdings), "warnings": []}


@app.get("/api/profile")
def get_profile() -> dict[str, Any]:
    return database.load_profile() or InvestorProfile().model_dump(mode="json")


@app.put("/api/profile")
def put_profile(profile: InvestorProfile) -> dict[str, Any]:
    return database.save_profile(profile.model_dump(mode="json"))


@app.post("/api/providers/refresh")
def refresh_providers(force: bool = Query(default=True)) -> dict[str, Any]:
    return refresh_scenarios(force=force)


@app.get("/api/scenarios")
def scenarios() -> dict[str, Any]:
    return refresh_scenarios(force=False)


@app.get("/api/research")
def research(tickers: str = Query(default="")) -> list[dict[str, Any]]:
    values = [ticker.strip().upper() for ticker in tickers.split(",") if ticker.strip()]
    return security_research(values[:50])


@app.post("/api/analyses")
def create_analysis(request: AnalysisRequest) -> dict[str, Any]:
    if request.portfolio is not None:
        holdings = [item.model_dump(mode="json") for item in request.portfolio.holdings]
    else:
        portfolios = database.list_portfolios()
        portfolio_id = request.portfolio_id or (portfolios[0]["id"] if portfolios else None)
        if portfolio_id is None:
            raise HTTPException(422, "A portfolio is required")
        try:
            holdings = database.get_portfolio(portfolio_id)["holdings"]
        except KeyError as exc:
            raise HTTPException(404, "Portfolio not found") from exc
    profile = request.profile or InvestorProfile.model_validate(database.load_profile() or {})
    result = run_analysis(holdings, profile)
    database.save_analysis(result["id"], request.model_dump(mode="json"), result)
    return result


@app.get("/api/analyses/{run_id}")
def get_analysis(run_id: str) -> dict[str, Any]:
    try:
        return database.load_analysis(run_id)
    except KeyError as exc:
        raise HTTPException(404, "Analysis run not found") from exc


@app.post("/api/analyses/{run_id}/explanation")
def explain(run_id: str, request: ExplanationRequest) -> dict[str, Any]:
    try:
        result = database.load_analysis(run_id)
    except KeyError as exc:
        raise HTTPException(404, "Analysis run not found") from exc
    return generate_explanation(result, request.provider, request.endpoint, request.model)
