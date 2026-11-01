import type {
  AggFunction,
  AggregationGroupBy,
  AggregationHaving,
  AggregationMetric,
  AggregationOrderBy,
  HavingOp,
  SortDirection,
} from "@/types/aggregation-types";

export type { AggFunction, HavingOp, SortDirection };

export type FilterOp =
  | "="
  | "!="
  | ">"
  | "<"
  | ">="
  | "<="
  | "like"
  | "ilike"
  | "in"
  | "not_in"
  | "between"
  | "is_null"
  | "is_not_null";

export type JoinHow = "inner" | "left" | "right" | "full";

export interface TableFilter {
  column: string;
  op: FilterOp;
  value: string | string[] | null;
}

export interface FormTable {
  name: string;
  alias: string;
  columns: string[];
  filters: TableFilter[];
}

export interface EntityJoin {
  left: string;
  right: string;
  leftOn: string;
  rightOn: string;
  how: JoinHow;
}

export type EntityGroupBy = AggregationGroupBy;

export type EntityAggregation = AggregationMetric;

export type EntityHaving = AggregationHaving;

export type EntityOrderBy = AggregationOrderBy;

export interface EntityFormState {
  name: string;
  description: string;
  mainTable: string;
  mainTableColumns: string[];
  mainTableFilters: TableFilter[];
  additionalTables: FormTable[];
  joins: EntityJoin[];
  aggregateMode: boolean;
  groupBy: EntityGroupBy[];
  aggregations: EntityAggregation[];
  having: EntityHaving[];
  orderBy: EntityOrderBy[];
}

export interface FieldInfo {
  name: string;
  type: string;
  // Valores del enum de PostgreSQL en orden de declaración; null si la columna no es un enum.
  enumValues: string[] | null;
}

/**
 * El campo con la configuración de la query (tables/joins/agregación) se llama
 * distinto en cada endpoint (filterCriteria en /segments/, reportConfig en
 * /reports/); use-entity-list.ts normaliza ambos a `config` al leer la respuesta.
 */
export interface EntityResponse {
  id: string;
  name: string;
  description: string | null;
  config: Record<string, unknown>;
  organizationId: string;
}

export interface EntityListResponse {
  items: EntityResponse[];
  total: number;
  page: number;
  pageSize: number;
}

export interface EntityExecuteRequest {
  mode: "preview" | "audit";
  limit?: number;
}

export interface EntityExecuteResponse {
  success: boolean;
  rows: number;
  columns: string[];
  data: Record<string, unknown>[];
  mode: string;
  fileName: string | null;
  filePath: string | null;
}

export interface EntityJobAccepted {
  message: string;
  reportId: string;
  mode: string;
}

export interface EntityExecutionResponse {
  id: string;
  entityId: string;
  mode: string;
  fileName: string | null;
  filePath: string | null;
  rows: number;
  columns: string[];
  executedBy: string;
}
