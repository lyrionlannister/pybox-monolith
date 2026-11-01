import type { FilterOp, JoinHow } from "@/query-builder/types/query-builder-types";

export { AGG_FUNCTIONS, HAVING_OPS, HAVING_OPS_WITH_MULTIPLE_VALUES } from "@/constants/aggregation-constants";

export const AUDIT_FIELDS = ["fecha_creacion", "fecha_actualizacion", "eliminado_en"];

export const FILTER_OPS: { value: FilterOp; label: string }[] = [
  { value: "=", label: "= (igual)" },
  { value: "!=", label: "≠ (distinto)" },
  { value: ">", label: "> (mayor)" },
  { value: "<", label: "< (menor)" },
  { value: ">=", label: "≥ (mayor o igual)" },
  { value: "<=", label: "≤ (menor o igual)" },
  { value: "like", label: "like" },
  { value: "ilike", label: "ilike (sin distinción de mayúsculas)" },
  { value: "in", label: "in (lista de valores)" },
  { value: "not_in", label: "not in" },
  { value: "between", label: "between (rango)" },
  { value: "is_null", label: "es nulo" },
  { value: "is_not_null", label: "no es nulo" },
];

export const JOIN_TYPES: { value: JoinHow; label: string }[] = [
  { value: "inner", label: "Inner join" },
  { value: "left", label: "Left join" },
  { value: "right", label: "Right join" },
  { value: "full", label: "Full outer join" },
];

/** Postgres no define LIKE/ILIKE sobre un enum (falla con "operator does not exist"). */
export const ENUM_UNSUPPORTED_OPS: FilterOp[] = ["like", "ilike"];

export const OPS_WITHOUT_VALUE: FilterOp[] = ["is_null", "is_not_null"];
export const OPS_WITH_MULTIPLE_VALUES: FilterOp[] = ["in", "not_in", "between"];

export const SQL_TYPE_LABELS: Record<string, string> = {
  "character varying": "texto",
  text: "texto",
  uuid: "uuid",
  integer: "entero",
  bigint: "entero",
  smallint: "entero",
  numeric: "número",
  "double precision": "número",
  boolean: "sí/no",
  date: "fecha",
  "timestamp with time zone": "fecha y hora",
  "timestamp without time zone": "fecha y hora",
  "USER-DEFINED": "categoría",
  jsonb: "json",
  json: "json",
};
