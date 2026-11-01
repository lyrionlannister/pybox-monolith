import type {
  AggregationGroupBy,
  AggregationHaving,
  AggregationMetric,
  AggregationOrderBy,
  AggregationStepState,
  AggregationTableRef,
} from "@/types/aggregation-types";

export type UseFieldsHook = (tableName: string) => { fields: { name: string }[] };

export interface StepAggregationCopy {
  /** "segmento" | "reporte" — usado en el texto de ayuda cuando aggregateMode está apagado. */
  entityNoun: string;
  /** Ejemplo de caso de uso mostrado junto al switch de agregación. */
  toggleHelpExample: string;
  /** Ejemplo de métrica mostrado en la descripción de HAVING (ej. "count_creditos"). */
  havingExampleMetric: string;
}

/**
 * El wizard de agregación nunca escribe mainTable/additionalTables (eso lo maneja
 * el paso de tablas); se omiten del patch para que el callback sea asignable a
 * EntityFormState (query-builder/), cuyo additionalTables lleva más campos.
 */
export type AggregationStepPatch = Partial<Omit<AggregationStepState, "mainTable" | "additionalTables">>;

export interface SharedStepAggregationProps {
  state: AggregationStepState;
  onUpdate: (patch: AggregationStepPatch) => void;
  useFields: UseFieldsHook;
  copy: StepAggregationCopy;
}

export interface AggregationSectionProps {
  title: string;
  description: string;
  onAdd: () => void;
  addLabel: string;
  disabled?: boolean;
  children: React.ReactNode;
}

export interface GroupByRowProps {
  group: AggregationGroupBy;
  tables: AggregationTableRef[];
  useFields: UseFieldsHook;
  onChange: (patch: Partial<AggregationGroupBy>) => void;
  onRemove: () => void;
}

export interface AggregationRowProps {
  aggregation: AggregationMetric;
  tables: AggregationTableRef[];
  useFields: UseFieldsHook;
  onChange: (patch: Partial<AggregationMetric>) => void;
  onRemove: () => void;
}

export interface HavingRowProps {
  having: AggregationHaving;
  metricOptions: string[];
  onChange: (patch: Partial<AggregationHaving>) => void;
  onRemove: () => void;
}

export interface OrderByRowProps {
  order: AggregationOrderBy;
  fieldOptions: string[];
  onChange: (patch: Partial<AggregationOrderBy>) => void;
  onRemove: () => void;
}
