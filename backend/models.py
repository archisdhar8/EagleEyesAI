from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


AccountType = Literal["taxable", "traditional_ira", "roth_ira", "401k", "other"]
Preset = Literal["growth", "balanced", "preservation", "income"]


class Holding(BaseModel):
    ticker: str = Field(min_length=1, max_length=10)
    shares: float | None = Field(default=None, ge=0)
    weight: float | None = Field(default=None, ge=0, le=1)
    market_value: float | None = Field(default=None, ge=0)
    cost_basis: float | None = Field(default=None, ge=0)
    account_type: AccountType = "taxable"
    acquisition_date: date | None = None

    @model_validator(mode="after")
    def require_position_size(self) -> "Holding":
        if self.shares is None and self.weight is None and self.market_value is None:
            raise ValueError("Provide shares, weight, or market_value")
        self.ticker = self.ticker.upper().strip()
        return self


class ObjectiveWeights(BaseModel):
    expected_return: float = Field(default=0.55, ge=0, le=1)
    volatility: float = Field(default=0.45, ge=0, le=1)
    drawdown: float = Field(default=0.55, ge=0, le=1)
    diversification: float = Field(default=0.65, ge=0, le=1)
    turnover: float = Field(default=0.35, ge=0, le=1)
    tax_drag: float = Field(default=0.35, ge=0, le=1)
    income: float = Field(default=0.15, ge=0, le=1)


class InvestorProfile(BaseModel):
    age: int = Field(default=35, ge=18, le=100)
    retirement_age: int = Field(default=65, ge=18, le=110)
    horizon_years: int = Field(default=20, ge=1, le=60)
    account_type: AccountType = "taxable"
    annual_contribution: float = Field(default=12000, ge=0)
    annual_withdrawal: float = Field(default=0, ge=0)
    target_value: float = Field(default=1_000_000, ge=0)
    tax_rate: float = Field(default=0.20, ge=0, le=0.60)
    risk_tolerance: int = Field(default=6, ge=1, le=10)
    preset: Preset = "balanced"
    restrictions: list[str] = Field(default_factory=list)
    watchlist: list[str] = Field(default_factory=lambda: ["SPY", "QQQ", "VTI", "XLE", "XLV"])
    objectives: ObjectiveWeights = Field(default_factory=ObjectiveWeights)
    llm_provider: Literal["disabled", "ollama", "openai_compatible"] = "disabled"
    llm_endpoint: str | None = None
    llm_model: str | None = None


class PortfolioPayload(BaseModel):
    name: str = Field(default="Primary portfolio", min_length=1, max_length=80)
    holdings: list[Holding] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def reject_duplicate_tickers(self) -> "PortfolioPayload":
        tickers = [holding.ticker.upper().strip() for holding in self.holdings]
        duplicates = sorted({ticker for ticker in tickers if tickers.count(ticker) > 1})
        if duplicates:
            raise ValueError(f"Duplicate tickers are not allowed: {', '.join(duplicates)}")
        return self


class Scenario(BaseModel):
    key: str
    label: str
    probability: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    change_1d: float | None = None
    change_1w: float | None = None
    change_1m: float | None = None
    indicators: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    as_of: datetime
    is_prior: bool = False


class AnalysisRequest(BaseModel):
    portfolio_id: str | int | None = None
    portfolio: PortfolioPayload | None = None
    profile: InvestorProfile | None = None


class ExplanationRequest(BaseModel):
    provider: Literal["disabled", "ollama", "openai_compatible"] = "disabled"
    endpoint: str | None = None
    model: str | None = None
