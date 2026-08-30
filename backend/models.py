from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


AccountType = Literal["taxable", "traditional_ira", "roth_ira", "401k", "other"]
Preset = Literal["growth", "balanced", "preservation", "income"]
DecisionType = Literal["WATCH", "BUY", "ADD", "HOLD", "REDUCE", "SELL", "AVOID"]
ThesisStatus = Literal["DRAFT", "ACTIVE", "UNDER_REVIEW", "CLOSED", "ARCHIVED"]
ThesisHorizon = Literal["short", "medium", "long", "custom"]
AssumptionCategory = Literal[
    "GROWTH", "PROFITABILITY", "MARGIN", "VALUATION", "BALANCE_SHEET",
    "COMPETITIVE_POSITION", "CAPITAL_ALLOCATION", "DEMAND", "MACRO",
    "MANAGEMENT", "REGULATORY", "PORTFOLIO_FIT", "CUSTOM",
]
AssumptionImportance = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
AssumptionStatus = Literal["UNTESTED", "SUPPORTED", "WEAKENING", "BROKEN", "NOT_MONITORABLE"]
ComparisonOperator = Literal[">", ">=", "<", "<=", "=", "!="]
ThesisFactorType = Literal["CATALYST", "RISK", "BREAKER"]


class ThesisAssumptionPayload(BaseModel):
    id: str | None = None
    description: str = Field(min_length=2, max_length=1000)
    category: AssumptionCategory = "CUSTOM"
    importance: AssumptionImportance = "MEDIUM"
    status: AssumptionStatus = "UNTESTED"
    metric: str | None = Field(default=None, max_length=120)
    operator: ComparisonOperator | None = None
    target_value: float | None = None
    unit: str | None = Field(default=None, max_length=40)
    evidence_mapping: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_monitorable_assumption(self) -> "ThesisAssumptionPayload":
        structured = [self.metric, self.operator, self.target_value]
        if any(value is not None for value in structured) and not all(value is not None for value in structured):
            raise ValueError("Monitorable assumptions require metric, operator, and target_value together")
        return self


class ThesisFactorPayload(BaseModel):
    id: str | None = None
    factor_type: ThesisFactorType
    description: str = Field(min_length=2, max_length=1000)
    metric: str | None = Field(default=None, max_length=120)
    operator: ComparisonOperator | None = None
    threshold: float | None = None
    period_requirement: str | None = Field(default=None, max_length=120)
    unit: str | None = Field(default=None, max_length=40)
    evidence_mapping: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_monitorable_factor(self) -> "ThesisFactorPayload":
        structured = [self.metric, self.operator, self.threshold]
        if any(value is not None for value in structured) and not all(value is not None for value in structured):
            raise ValueError("Monitorable factors require metric, operator, and threshold together")
        return self


class InvestmentThesisPayload(BaseModel):
    ticker: str = Field(min_length=1, max_length=10, pattern=r"^[A-Za-z][A-Za-z0-9.-]{0,9}$")
    summary: str = Field(min_length=2, max_length=2000)
    base_case: str = Field(default="", max_length=4000)
    bull_case: str = Field(default="", max_length=4000)
    bear_case: str = Field(default="", max_length=4000)
    investment_horizon: ThesisHorizon = "long"
    horizon_end_date: date | None = None
    review_date: date | None = None
    status: ThesisStatus = "DRAFT"
    source_context: dict[str, Any] = Field(default_factory=dict)
    change_note: str | None = Field(default=None, max_length=500)
    assumptions: list[ThesisAssumptionPayload] = Field(default_factory=list, max_length=50)
    factors: list[ThesisFactorPayload] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def normalize_ticker(self) -> "InvestmentThesisPayload":
        self.ticker = self.ticker.upper().strip()
        return self


class InvestmentDecisionPayload(BaseModel):
    ticker: str = Field(min_length=1, max_length=10, pattern=r"^[A-Za-z][A-Za-z0-9.-]{0,9}$")
    thesis_id: str | None = None
    decision_type: DecisionType
    decision_date: datetime | None = None
    quantity: float | None = Field(default=None, ge=0)
    portfolio_context: dict[str, Any] = Field(default_factory=dict)
    user_confidence: int | None = Field(default=None, ge=1, le=5)
    investment_horizon: ThesisHorizon | None = None
    notes: str = Field(default="", max_length=4000)
    source_context: dict[str, Any] = Field(default_factory=dict)
    expected_outcome: str = Field(default="", max_length=4000)
    review_horizon_days: int | None = Field(default=None, ge=30, le=3650)
    comparison_benchmark: str = Field(default="SPY", min_length=1, max_length=10, pattern=r"^[A-Za-z][A-Za-z0-9.-]{0,9}$")

    @model_validator(mode="after")
    def normalize_decision_ticker(self) -> "InvestmentDecisionPayload":
        self.ticker = self.ticker.upper().strip()
        self.comparison_benchmark = self.comparison_benchmark.upper().strip()
        return self


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
    inflation_rate: float = Field(default=.025, ge=0, le=.25)
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


EconomicState = Literal["unconditioned", "expansion", "slowdown", "recession"]
InflationState = Literal["unconditioned", "cooling", "stable", "accelerating"]
RateState = Literal["unconditioned", "easing", "stable", "tightening"]


class SimulationScenario(BaseModel):
    economic_state: EconomicState = "unconditioned"
    inflation_state: InflationState = "unconditioned"
    rate_state: RateState = "unconditioned"
    shocks: list[Literal["oil", "credit", "geopolitical"]] = Field(default_factory=list)


class SimulationStrategy(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    weights: dict[str, float]
    transition_months: int = Field(default=0, ge=0, le=120)
    contribution_weights: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_weights(self) -> "SimulationStrategy":
        if not self.weights or any(value < 0 or value > 1 for value in self.weights.values()):
            raise ValueError("Strategy weights must be decimal values between 0 and 1")
        total = sum(self.weights.values())
        if total <= 0:
            raise ValueError("Strategy weights must have a positive total")
        self.weights = {ticker.upper(): value / total for ticker, value in self.weights.items()}
        if self.contribution_weights:
            contribution_total = sum(self.contribution_weights.values())
            if contribution_total > 0:
                self.contribution_weights = {
                    ticker.upper(): value / contribution_total
                    for ticker, value in self.contribution_weights.items()
                }
        return self


class SimulationRunInput(BaseModel):
    portfolio_id: str | int | None = None
    holdings: list[Holding] = Field(min_length=1, max_length=500)
    profile: InvestorProfile = Field(default_factory=InvestorProfile)
    goals: list[FinancialGoal] = Field(default_factory=list, max_length=25)
    scenario: SimulationScenario = Field(default_factory=SimulationScenario)
    strategies: list[SimulationStrategy] = Field(default_factory=list, max_length=12)
    horizon_years: int | None = Field(default=None, ge=1, le=60)
    paths: int = Field(default=5000, ge=250, le=10000)
    block_months: int = Field(default=6, ge=1, le=24)
    seed: int = Field(default=90210, ge=0, le=2_147_483_647)


class ETFAllocationRequest(BaseModel):
    candidate_tickers: list[str] = Field(default_factory=list, max_length=100)
    current_holdings: list[Holding] = Field(default_factory=list, max_length=500)
    objective: Literal["balanced", "lower_downside", "income", "growth", "lowest_cost"] = "balanced"
    time_horizon_years: int = Field(default=15, ge=1, le=60)
    risk_tolerance: int = Field(default=6, ge=1, le=10)
    loss_capacity: int = Field(default=6, ge=1, le=10)
    income_stability: Literal["unstable", "variable", "stable"] = "stable"
    initial_investment: float = Field(default=10_000, ge=0)
    annual_contribution: float = Field(default=0, ge=0)
    annual_withdrawal: float = Field(default=0, ge=0)
    account_type: AccountType = "taxable"
    tax_rate: float = Field(default=.20, ge=0, le=.60)
    required_asset_classes: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    max_expense_ratio: float = Field(default=.01, ge=0, le=.10)
    minimum_history_years: float = Field(default=3, ge=0, le=30)
    minimum_liquidity: float = Field(default=0, ge=0)
    max_fund_weight: float = Field(default=.40, ge=.01, le=1)
    max_issuer_weight: float = Field(default=.60, ge=.01, le=1)
    excluded_tickers: list[str] = Field(default_factory=list)
    excluded_sectors: list[str] = Field(default_factory=list)


class StockBasketRequest(BaseModel):
    candidate_tickers: list[str] = Field(min_length=1, max_length=100)
    current_holdings: list[Holding] = Field(default_factory=list, max_length=500)
    benchmark: str = Field(default="SPY", min_length=1, max_length=10)
    objective: Literal[
        "diversification", "lower_downside", "quality_growth", "value", "income",
        "macro_resilience", "custom",
    ] = "diversification"
    factor_weights: dict[str, float] = Field(default_factory=dict)
    max_security_weight: float = Field(default=.20, ge=.01, le=1)
    max_sector_weight: float = Field(default=.40, ge=.01, le=1)
    max_industry_weight: float = Field(default=.30, ge=.01, le=1)
    minimum_history_years: float = Field(default=3, ge=0, le=30)
    minimum_data_quality: Literal["low", "medium", "high"] = "medium"
    excluded_tickers: list[str] = Field(default_factory=list)
    tax_rate: float = Field(default=.20, ge=0, le=.60)
    turnover_limit: float = Field(default=1, ge=0, le=1)


class ModelPortfolioCompareRequest(BaseModel):
    portfolio_type: Literal["stocks", "etfs", "mixed"] = "mixed"
    candidate_tickers: list[str] = Field(min_length=2, max_length=100)
    benchmark: str = Field(default="SPY", min_length=1, max_length=10)
    factor_weights: dict[str, float] = Field(default_factory=dict)
    max_security_weight: float = Field(default=.25, ge=.01, le=1)
    max_expense_ratio: float = Field(default=.01, ge=0, le=.10)
    minimum_history_years: float = Field(default=3, ge=0, le=30)

    @model_validator(mode="after")
    def normalize_candidates(self) -> "ModelPortfolioCompareRequest":
        self.candidate_tickers = list(dict.fromkeys(
            ticker.strip().upper() for ticker in self.candidate_tickers if ticker.strip()
        ))
        self.benchmark = self.benchmark.strip().upper()
        return self


class ModelPortfolioBacktestRequest(BaseModel):
    alternatives: dict[str, dict[str, float]] = Field(min_length=1, max_length=12)
    benchmark: str = Field(default="SPY", min_length=1, max_length=10)
    start_date: date | None = None
    end_date: date | None = None
    rebalance_policy: Literal["monthly", "quarterly", "annual", "buy_and_hold"] = "monthly"
    transaction_cost_bps: float | None = Field(default=None, ge=0, le=500)

    @model_validator(mode="after")
    def validate_period(self) -> "ModelPortfolioBacktestRequest":
        if self.start_date and self.end_date and self.start_date >= self.end_date:
            raise ValueError("Backtest start_date must be before end_date")
        self.benchmark = self.benchmark.strip().upper()
        return self


class ModelPortfolioPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    portfolio_type: Literal["stocks", "etfs", "mixed"] = "mixed"
    status: Literal["draft", "saved", "converted"] = "draft"
    candidate_universe: dict[str, Any] = Field(default_factory=dict)
    basket: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    configuration: dict[str, Any] = Field(default_factory=dict)
    comparison_results: dict[str, Any] = Field(default_factory=dict)
    backtest_results: dict[str, Any] = Field(default_factory=dict)
    simulation_run_id: str | None = None


class ModelPortfolioConversionRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    alternative_key: str = Field(default="balanced", min_length=1, max_length=80)
    initial_value: float = Field(default=10_000, gt=0)
    account_type: AccountType = "taxable"


class ETFAllocationResult(BaseModel):
    id: str | None = None
    builder_type: Literal["etf"] = "etf"
    model_version: str
    objective: str
    universe: dict[str, Any]
    allocations: list[dict[str, Any]]
    portfolio_metrics: dict[str, Any]
    benchmarks: list[dict[str, Any]] = Field(default_factory=list)
    overlap: list[dict[str, Any]] = Field(default_factory=list)
    constraints: dict[str, Any]
    lineage: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class StockBasketResult(BaseModel):
    id: str | None = None
    builder_type: Literal["stock"] = "stock"
    model_version: str
    objective: str
    universe: dict[str, Any]
    allocations: list[dict[str, Any]]
    portfolio_metrics: dict[str, Any]
    benchmarks: list[dict[str, Any]] = Field(default_factory=list)
    constraints: dict[str, Any]
    lineage: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SecurityResearchSnapshot(BaseModel):
    ticker: str
    as_of: datetime
    market: dict[str, Any] = Field(default_factory=dict)
    fundamentals: dict[str, Any] = Field(default_factory=dict)
    valuation: dict[str, Any] = Field(default_factory=dict)
    technicals: dict[str, Any] = Field(default_factory=dict)
    sentiment: dict[str, Any] = Field(default_factory=dict)
    conclusions: dict[str, str] = Field(default_factory=dict)
    lineage: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    calculation_version: str


class SimulationOutcome(BaseModel):
    strategy_key: str
    wealth_percentiles: dict[str, float]
    real_wealth_percentiles: dict[str, float]
    probability_of_loss: float
    terminal_loss_probability: float | None = None
    terminal_return_percentiles: dict[str, float] = Field(default_factory=dict)
    simulated_max_drawdown_p95: float | None = None
    historical_max_drawdown: float | None = None
    drawdown_breach_probability: float | None = None
    drawdown_percentiles: dict[str, float]
    recovery_months: dict[str, float | None]
    goal_results: list[dict[str, Any]] = Field(default_factory=list)
    turnover: float
    estimated_taxes: float | None = None
    estimated_fees: float
    concentration: dict[str, float]
    scenario_summary: dict[str, Any]
    regret: float
    robustness: str
    representative_paths: list[list[float]] = Field(default_factory=list)
    histograms: dict[str, dict[str, list[float | int]]] = Field(default_factory=dict)


class SimulationRun(BaseModel):
    id: str
    input: SimulationRunInput
    outcomes: list[SimulationOutcome]
    shared_path_fingerprint: str
    model_version: str
    created_at: datetime
    lineage: list[dict[str, Any]]
    assumptions: list[str]
    warnings: list[str]
