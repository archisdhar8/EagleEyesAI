export const AI_DASHBOARD_SPEC_VERSION = "dashboard-spec-v2";
export const AI_DASHBOARD_LAYOUT_VERSION = "dashboard-layout-v2";

export type DashboardDataBinding = {
  metric: string;
  portfolio?: string | null;
  benchmark?: string | null;
  period: "1M" | "3M" | "6M" | "1Y" | "3Y" | "5Y" | "7Y" | "10Y" | "20Y";
  tickers: string[];
  filters: Array<{ field: string; operator: "eq" | "neq" | "contains" | "in"; value: string | string[] }>;
};

export type DashboardWidgetSpec = {
  id: string;
  task_id: string;
  widget_type: string;
  title: string;
  visualization: string;
  grid: { x: number; y: number; w: number; h: number };
  binding?: DashboardDataBinding | null;
  source_result_id?: string;
  source_capability?: string;
  source_category?: "VERIFIED" | "MODEL_OUTPUT" | "MARKET_IMPLIED" | "USER_THESIS";
  field_mapping?: { data_path: string; shape: "scalar" | "category" | "time_series" | "matrix" | "records" | "distribution"; label_field?: string | null; value_field?: string | null; time_field?: string | null };
  state?: "CURRENT" | "STALE" | "REFRESHING" | "PARTIAL" | "UNAVAILABLE" | "FAILED" | "PENDING";
  job_reference?: Record<string, unknown> | null;
};

export type DashboardAction =
  | { type: "CREATE_WIDGET"; widget: Omit<DashboardWidgetSpec, "id"> & { id?: string } }
  | { type: "UPDATE_WIDGET"; widget_id: string; changes: { title?: string; visualization?: string; binding?: DashboardDataBinding } }
  | { type: "DELETE_WIDGET"; widget_id: string }
  | { type: "MOVE_WIDGET"; widget_id: string; to_index?: number; position?: { x: number; y: number } }
  | { type: "RESIZE_WIDGET"; widget_id: string; width: number; height: number }
  | { type: "CHANGE_VISUALIZATION"; widget_id: string; visualization: string }
  | { type: "UPDATE_FILTER"; widget_id: string; filters: DashboardDataBinding["filters"] }
  | { type: "UPDATE_DATE_RANGE"; widget_id: string; period: DashboardDataBinding["period"] }
  | { type: "CLEAR_DASHBOARD" }
  | { type: "RENAME_DASHBOARD"; name: string };

export type DashboardActionStatus = "SUCCESS" | "FAILED" | "INVALID" | "UNSUPPORTED";

export type DashboardActionResult<TDashboard = unknown> = {
  version: "dashboard-action-v1";
  status: DashboardActionStatus;
  action?: DashboardAction | null;
  dashboard?: TDashboard | null;
  revision?: Record<string, unknown> | null;
  error?: string | null;
};

export type DashboardSpecification = {
  version: string;
  spec_version: string;
  layout_version: string;
  title: string;
  description: string;
  compiler_version: string;
  widgets: DashboardWidgetSpec[];
  [key: string]: unknown;
};

export function adaptDashboardSpecification(value: unknown): DashboardSpecification {
  if (!value || typeof value !== "object") throw new Error("Invalid dashboard specification");
  const source = value as Record<string, unknown>;
  if (typeof source.title !== "string" || typeof source.description !== "string" || typeof source.compiler_version !== "string" || !Array.isArray(source.widgets)) {
    throw new Error("Unsupported dashboard specification contract");
  }
  const widgets = source.widgets.map((item) => {
    if (!item || typeof item !== "object") throw new Error("Invalid dashboard widget specification");
    const row = item as Record<string, unknown>;
    const grid = row.grid as Record<string, unknown> | undefined;
    if (!grid || typeof row.id !== "string" || typeof row.task_id !== "string" || typeof row.widget_type !== "string") {
      throw new Error("Unsupported dashboard widget specification");
    }
    return {
      ...row,
      id: row.id,
      task_id: row.task_id,
      widget_type: row.widget_type,
      title: String(row.title || row.widget_type),
      visualization: String(row.visualization || "cards"),
      grid: { x: Number(grid.x), y: Number(grid.y), w: Number(grid.w), h: Number(grid.h) },
    } as DashboardWidgetSpec;
  });
  const version = typeof source.version === "string" ? source.version : "dashboard-spec-v1";
  return {
    ...source,
    version,
    spec_version: typeof source.spec_version === "string" ? source.spec_version : version,
    layout_version: typeof source.layout_version === "string" ? source.layout_version : "dashboard-layout-v1",
    title: source.title, description: source.description, compiler_version: source.compiler_version, widgets,
  } as DashboardSpecification;
}
