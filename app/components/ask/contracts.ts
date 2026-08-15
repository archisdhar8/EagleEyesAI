export const AI_DASHBOARD_SPEC_VERSION = "dashboard-spec-v2";
export const AI_DASHBOARD_LAYOUT_VERSION = "dashboard-layout-v2";

export type DashboardWidgetSpec = {
  id: string;
  task_id: string;
  widget_type: string;
  title: string;
  visualization: string;
  grid: { x: number; y: number; w: number; h: number };
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
