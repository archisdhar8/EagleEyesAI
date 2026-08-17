export type DecisionType = "WATCH" | "BUY" | "ADD" | "HOLD" | "REDUCE" | "SELL" | "AVOID";
export type ThesisStatus = "DRAFT" | "ACTIVE" | "UNDER_REVIEW" | "CLOSED" | "ARCHIVED";
export type ThesisHorizon = "short" | "medium" | "long" | "custom";
export type FactorType = "CATALYST" | "RISK" | "BREAKER";

export type ThesisAssumption = {
  id?: string;
  description: string;
  category: string;
  importance: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  status: "UNTESTED" | "SUPPORTED" | "WEAKENING" | "BROKEN" | "NOT_MONITORABLE";
  metric?: string | null;
  operator?: ">" | ">=" | "<" | "<=" | "=" | "!=" | null;
  target_value?: number | null;
  unit?: string | null;
  evidence_mapping: Record<string, unknown>;
};

export type ThesisFactor = {
  id?: string;
  factor_type: FactorType;
  description: string;
  metric?: string | null;
  operator?: ">" | ">=" | "<" | "<=" | "=" | "!=" | null;
  threshold?: number | null;
  period_requirement?: string | null;
  unit?: string | null;
  evidence_mapping: Record<string, unknown>;
};

export type InvestmentThesis = {
  id?: string;
  ticker: string;
  summary: string;
  base_case: string;
  bull_case: string;
  bear_case: string;
  investment_horizon: ThesisHorizon;
  horizon_end_date?: string | null;
  review_date?: string | null;
  status: ThesisStatus;
  source_context: Record<string, unknown>;
  current_version?: number;
  assumptions: ThesisAssumption[];
  factors: ThesisFactor[];
  created_at?: string;
  updated_at?: string;
  monitor_status?: ThesisMonitorSummary | null;
};

export type ThesisMonitorSummary = {overall_status:string;requires_review:boolean;reviewed_at:string;counts:Record<string,number>};
export type MonitoringEvidence = {evidence_type:string;metric:string;label:string;relevance:string;relationship:string;previous_value:number|string|boolean|null;current_value:number|string|boolean|null;unit?:string|null;absolute_change?:number|null;percent_change?:number|null;percentage_point_change?:number|null;direction:string;materiality:string;source:string;source_references:string[];previous_as_of?:string|null;current_as_of?:string|null;freshness:string;evidence_quality:string;methodology?:string|null;independence_group:string;metadata?:{current_metadata?:{market_quality?:string;volume?:number|null;spread?:number|null;resolution_date?:string|null;freshness_hours?:number|null}}};
export type AssumptionMonitorResult = {assumption_id:string;description:string;category:string;importance:string;state:string;condition_met?:boolean|null;deterministic:boolean;relevance_confidence:string;data_coverage:string;freshness:string;evidence_quality:string;evidence_agreement:string;evidence:MonitoringEvidence[];unrelated_evidence_count:number;explanation:string;rule?:string|null};
export type FactorMonitorResult = {factor_id:string;factor_type:"RISK"|"CATALYST"|"BREAKER";description:string;state:string;condition_met?:boolean|null;deterministic:boolean;periods_required:number;periods_evaluated:number;threshold_distance?:number|null;evidence_agreement:string;evidence:MonitoringEvidence[];explanation:string;rule?:string|null};
export type ThesisMonitorResult = {thesis_id:string;thesis_version:number;ticker:string;baseline_review_at:string;evaluated_at:string;overall_status:string;requires_review:boolean;assumption_results:AssumptionMonitorResult[];risk_results:FactorMonitorResult[];catalyst_results:FactorMonitorResult[];thesis_breaker_results:FactorMonitorResult[];evidence_coverage:Array<{evidence_type:string;status:string;observation_count:number;message:string}>;freshness:string;evidence_quality:string;counts:Record<string,number>;warnings:string[];calculation_version:string};

export type InvestmentDecision = {
  id: string;
  ticker: string;
  thesis_id?: string | null;
  thesis_version?: number | null;
  decision_type: DecisionType;
  decision_date: string;
  price_at_decision?: number | null;
  price_as_of?: string | null;
  price_source?: string | null;
  quantity?: number | null;
  user_confidence?: number | null;
  notes: string;
  source_context?: {expected_outcome?:string;review_horizon_days?:number|null;comparison_benchmark?:string;[key:string]:unknown};
  snapshot_available?: boolean;
  snapshot_missing_reason?: string | null;
};

export type DecisionSnapshot = {decision_id:string;ticker:string;decision_type:DecisionType;decision_date:string;price:{value?:number|null;as_of?:string|null;provider?:string|null};thesis?:InvestmentThesis|null;expected_outcome:string;review_horizon_days?:number|null;comparison_benchmark:string;user_confidence?:number|null;portfolio:{status:string;normalized_weight?:number|null;reason?:string};forecasts:Array<Record<string,unknown>>;prediction_markets:Array<Record<string,unknown>>;missing:string[];methodology:string};
export type DecisionRetrospective = {version:string;decision:InvestmentDecision;snapshot:DecisionSnapshot;horizon:{key:string;start:string;end:string;matured:boolean};thesis_outcomes:{assumptions:Array<{description:string;category?:string;importance?:string;status:string;observed?:number|null;rule?:string|null}>;risks:Array<{description:string;status:string}>;catalysts:Array<{description:string;status:string}>;breakers:Array<{description:string;status:string}>};market_outcome:{security:string;security_return?:number|null;benchmark:string;benchmark_return?:number|null;relative_return?:number|null;status:string;methodology:string};process_review:{thesis_support:string;confirmed_assumptions:number;invalidated_assumptions:number;interpretation:string};evidence_timeline:Array<{type:string;at:string;title:string;materiality?:string}>;warnings:string[];grounded_summary:string;methodology:string};
export type DecisionJournalWorkspace = {version:string;recent_decisions:InvestmentDecision[];ready_for_review:Array<{decision:InvestmentDecision;due_at:string;horizon_days:number}>;completed_retrospectives:Array<{id:string;decision_id:string;horizon_key:string;window_end:string;user_notes:string;reviewed_at:string;structured_result:DecisionRetrospective}>;patterns:{reviewed_decisions:number;minimum_sample:number;status:string;patterns:Array<{pattern:string;count:number;sample_size:number;established:boolean;message:string}>};forecast_calibration:{sample_size:number;brier_score?:number|null;status:string;message?:string|null;buckets:Array<{range:string;n:number;resolved_yes_rate:number}>;methodology:string}};

export type DecisionsWorkspace = {
  active_theses: InvestmentThesis[];
  recent_decisions: InvestmentDecision[];
  needs_thesis: Array<{ ticker: string; source: "holding" | "watchlist" }>;
  review_dates: InvestmentThesis[];
  contexts: Record<string, {
    has_open_thesis: boolean;
    thesis_id?: string | null;
    thesis_status?: ThesisStatus | null;
    review_date?: string | null;
    latest_decision?: DecisionType | null;
    latest_decision_date?: string | null;
  }>;
  monitor_statuses?: Record<string, ThesisMonitorSummary>;
};
