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


class MajorDebt(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    balance: float = Field(default=0, ge=0)
    interest_rate: float = Field(default=0, ge=0, le=1)
    minimum_monthly_payment: float = Field(default=0, ge=0)


class NearTermPurchase(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    amount: float = Field(default=0, ge=0)
    target_date: date | None = None


class SuitabilityProfile(BaseModel):
    version: Literal["suitability-v1"] = "suitability-v1"
    guidance_level: Literal["research_only", "guided_analysis", "recommendations"] = "research_only"
    investing_experience: Literal["beginner", "intermediate", "advanced"] = "intermediate"
    required_risk: int = Field(default=5, ge=1, le=10)
    liquidity_needs_next_24_months: float = Field(default=0, ge=0)
    income_stability: Literal["unstable", "variable", "stable"] = "stable"
    household_annual_income: float = Field(default=0, ge=0)
    emergency_reserve_months: float = Field(default=0, ge=0, le=60)
    major_debts: list[MajorDebt] = Field(default_factory=list)
    near_term_purchases: list[NearTermPurchase] = Field(default_factory=list)
    employer_stock_ticker: str | None = Field(default=None, max_length=10)
    employer_stock_value: float = Field(default=0, ge=0)
    household_status: Literal["single", "partnered", "household"] = "single"
    dependents: int = Field(default=0, ge=0, le=20)
    outside_accounts_value: float = Field(default=0, ge=0)
    outside_accounts_notes: str = Field(default="", max_length=1000)


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
    loss_capacity: int = Field(default=6, ge=1, le=10)
    annual_income_need: float = Field(default=0, ge=0)
    preset: Preset = "balanced"
    restrictions: list[str] = Field(default_factory=list)
    watchlist: list[str] = Field(default_factory=lambda: ["SPY", "QQQ", "VTI", "XLE", "XLV"])
    objectives: ObjectiveWeights = Field(default_factory=ObjectiveWeights)
    research_preferences: dict[str, float] = Field(default_factory=lambda: {
        "fundamentals": .25, "growth": .20, "valuation": .20, "dividend_income": .10,
        "macro_resilience": .15, "price_behavior": .10,
    })
    suitability_profile: SuitabilityProfile = Field(default_factory=SuitabilityProfile)
    llm_provider: Literal["disabled", "ollama", "openai_compatible"] = "disabled"
    llm_endpoint: str | None = None
    llm_model: str | None = None

    @model_validator(mode="after")
    def validate_research_preferences(self) -> "InvestorProfile":
        total = sum(self.research_preferences.values())
        if total > 0:
            self.research_preferences = {key: value / total for key, value in self.research_preferences.items()}
        return self


GoalType = Literal[
    "retirement", "home_purchase", "education", "emergency_reserve",
    "income", "wealth_preservation", "long_term_growth", "other",
]


class FinancialGoal(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=100)
    goal_type: GoalType = "long_term_growth"
    target_amount: float = Field(gt=0)
    target_date: date
    current_value: float = Field(default=0, ge=0)
    annual_contribution: float = Field(default=0, ge=0)
    priority: int = Field(default=3, ge=1, le=5)
    funding_source: str = Field(default="New contributions", min_length=1, max_length=120)
    flexibility: Literal["fixed", "somewhat_flexible", "very_flexible"] = "somewhat_flexible"
    inflation_adjusted: bool = True
    account_allocations: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_allocations(self) -> "FinancialGoal":
        for account, allocation in self.account_allocations.items():
            if not account.strip() or allocation < 0 or allocation > 1:
                raise ValueError("Goal account allocations must be decimal values between 0 and 1")
        return self


class GoalProjectionRequest(BaseModel):
    goal: FinancialGoal
    risk_tolerance: int = Field(default=6, ge=1, le=10)
    additional_annual_contribution: float = Field(default=0, ge=0)


class InvestmentPolicy(BaseModel):
    id: str | None = None
    name: str = Field(default="Personal investment policy", min_length=1, max_length=100)
    status: Literal["draft", "approved"] = "draft"
    target_allocation: dict[str, float] = Field(default_factory=lambda: {"equities": .70, "fixed_income": .20, "cash": .10})
    acceptable_ranges: dict[str, list[float]] = Field(default_factory=lambda: {"equities": [.60, .80], "fixed_income": [.10, .30], "cash": [.05, .15]})
    minimum_cash_reserve: float = Field(default=10_000, ge=0)
    max_single_stock_weight: float = Field(default=.20, ge=.01, le=1)
    max_sector_weight: float = Field(default=.35, ge=.01, le=1)
    rebalance_threshold: float = Field(default=.05, ge=.01, le=.50)
    rebalance_frequency: Literal["monthly", "quarterly", "semiannual", "annual"] = "quarterly"
    exclusions: list[str] = Field(default_factory=list)
    change_triggers: list[str] = Field(default_factory=lambda: [
        "A goal, cash-flow need, or time horizon changes materially",
        "An allocation moves outside its approved range",
        "Portfolio risk exceeds the approved loss capacity",
    ])
    ignore_conditions: list[str] = Field(default_factory=lambda: [
        "Ordinary market volatility",
        "Short-term price forecasts without corroborating evidence",
        "A single news headline that does not change the investment thesis",
    ])
    research_preferences: dict[str, float] = Field(default_factory=lambda: {
        "fundamentals": .25, "growth": .20, "valuation": .20, "dividend_income": .10,
        "macro_resilience": .15, "price_behavior": .10,
    })
    approved_at: datetime | None = None

    @model_validator(mode="after")
    def validate_policy(self) -> "InvestmentPolicy":
        for key, value in self.target_allocation.items():
            if not key.strip() or value < 0 or value > 1:
                raise ValueError("Target allocations must be decimal values between 0 and 1")
        allocation_total = sum(self.target_allocation.values())
        if allocation_total > 0:
            self.target_allocation = {key: value / allocation_total for key, value in self.target_allocation.items()}
        for key, bounds in self.acceptable_ranges.items():
            if len(bounds) != 2 or not 0 <= bounds[0] <= bounds[1] <= 1:
                raise ValueError(f"Invalid acceptable range for {key}")
        preference_total = sum(self.research_preferences.values())
        if preference_total > 0:
            self.research_preferences = {key: value / preference_total for key, value in self.research_preferences.items()}
        return self


class PortfolioPayload(BaseModel):
    name: str = Field(default="Primary portfolio", min_length=1, max_length=80)
    holdings: list[Holding] = Field(min_length=1, max_length=500)

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


class TransactionCsvImport(BaseModel):
    account_id: str = Field(min_length=1, max_length=120)
    csv_text: str = Field(min_length=1, max_length=5_000_000)
    save: bool = False


class AccountPerformanceRequest(BaseModel):
    account_id: str = Field(min_length=1, max_length=120)
    transactions: list[dict] = Field(default_factory=list, max_length=100_000)
    valuations: list[dict] = Field(default_factory=list, max_length=20_000)


class StatementReconciliationRequest(BaseModel):
    account_id: str = Field(min_length=1, max_length=120)
    statement_date: date
    statement_market_value: float = Field(ge=0)
    statement_cash: float
    reconstructed_market_value: float = Field(ge=0)
    reconstructed_cash: float
    tolerance: float = Field(default=1.0, ge=0, le=100_000)


class ExplanationRequest(BaseModel):
    provider: Literal["disabled", "ollama", "openai_compatible"] = "disabled"
    endpoint: str | None = None
    model: str | None = None
