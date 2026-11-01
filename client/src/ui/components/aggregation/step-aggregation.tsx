import { Switch } from "@/ui/components/switch";
import type {
  AggregationGroupBy,
  AggregationHaving,
  AggregationMetric,
  AggregationOrderBy,
  AggregationTableRef,
} from "@/types/aggregation-types";
import type { SharedStepAggregationProps } from "@/ui/types/step-aggregation-props";
import { AggregationSection } from "./aggregation-section";
import { GroupByRow } from "./group-by-row";
import { AggregationRow } from "./aggregation-row";
import { HavingRow } from "./having-row";
import { OrderByRow } from "./order-by-row";

export const StepAggregation: React.FC<SharedStepAggregationProps> = ({
  state,
  onUpdate,
  useFields,
  copy,
}) => {
  const tables: AggregationTableRef[] = [
    { alias: state.mainTable, name: state.mainTable },
    ...state.additionalTables.map((t) => ({ alias: t.alias, name: t.name })),
  ];

  const metricOptions = state.aggregations.map((a) => a.alias).filter(Boolean);
  const fieldOptions = [...state.groupBy.map((g) => g.alias), ...metricOptions].filter(Boolean);

  const addGroupBy = () => {
    const firstTable = tables[0];
    const group: AggregationGroupBy = { table: firstTable?.alias ?? "", column: "", alias: "" };
    onUpdate({ groupBy: [...state.groupBy, group] });
  };

  const updateGroupBy = (i: number, patch: Partial<AggregationGroupBy>) =>
    onUpdate({ groupBy: state.groupBy.map((g, idx) => (idx === i ? { ...g, ...patch } : g)) });

  const removeGroupBy = (i: number) =>
    onUpdate({ groupBy: state.groupBy.filter((_, idx) => idx !== i) });

  const addAggregation = () => {
    const firstTable = tables[0];
    const aggregation: AggregationMetric = {
      function: "count",
      table: firstTable?.alias ?? "",
      column: "*",
      alias: `count_${state.aggregations.length + 1}`,
    };
    onUpdate({ aggregations: [...state.aggregations, aggregation] });
  };

  const updateAggregation = (i: number, patch: Partial<AggregationMetric>) =>
    onUpdate({ aggregations: state.aggregations.map((a, idx) => (idx === i ? { ...a, ...patch } : a)) });

  const removeAggregation = (i: number) => {
    const removedAlias = state.aggregations[i]?.alias;
    onUpdate({
      aggregations: state.aggregations.filter((_, idx) => idx !== i),
      having: state.having.filter((h) => h.metric !== removedAlias),
      orderBy: state.orderBy.filter((o) => o.field !== removedAlias),
    });
  };

  const addHaving = () => {
    const firstMetric = metricOptions[0] ?? "";
    const having: AggregationHaving = { metric: firstMetric, op: ">", value: "" };
    onUpdate({ having: [...state.having, having] });
  };

  const updateHaving = (i: number, patch: Partial<AggregationHaving>) =>
    onUpdate({ having: state.having.map((h, idx) => (idx === i ? { ...h, ...patch } : h)) });

  const removeHaving = (i: number) =>
    onUpdate({ having: state.having.filter((_, idx) => idx !== i) });

  const addOrderBy = () => {
    const order: AggregationOrderBy = { field: fieldOptions[0] ?? "", direction: "desc" };
    onUpdate({ orderBy: [...state.orderBy, order] });
  };

  const updateOrderBy = (i: number, patch: Partial<AggregationOrderBy>) =>
    onUpdate({ orderBy: state.orderBy.map((o, idx) => (idx === i ? { ...o, ...patch } : o)) });

  const removeOrderBy = (i: number) =>
    onUpdate({ orderBy: state.orderBy.filter((_, idx) => idx !== i) });

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 dark:border-gray-700 dark:bg-white/3">
        <div>
          <p className="text-sm font-medium text-gray-700 dark:text-gray-200">Agrupar y agregar resultados</p>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Activa esto para usar COUNT, SUM, AVG, MIN o MAX (por ejemplo: {copy.toggleHelpExample}).
          </p>
        </div>
        <Switch
          checked={state.aggregateMode}
          onChange={(checked) => onUpdate({ aggregateMode: checked })}
          ariaLabel="Agrupar y agregar resultados"
        />
      </div>

      {!state.aggregateMode ? (
        <p className="text-xs text-gray-400 dark:text-gray-500">
          El {copy.entityNoun} devolverá el detalle fila por fila, sin agrupar.
        </p>
      ) : (
        <>
          <AggregationSection
            title="Agrupar por"
            description="Columnas usadas para agrupar las filas (ej. id del deudor)."
            onAdd={addGroupBy}
            addLabel="Agregar columna"
          >
            {state.groupBy.length === 0 ? (
              <p className="text-xs text-gray-400 dark:text-gray-500">Sin columnas de agrupación.</p>
            ) : (
              <div className="space-y-2">
                {state.groupBy.map((g, i) => (
                  <GroupByRow
                    key={i}
                    group={g}
                    tables={tables}
                    useFields={useFields}
                    onChange={(patch) => updateGroupBy(i, patch)}
                    onRemove={() => removeGroupBy(i)}
                  />
                ))}
              </div>
            )}
          </AggregationSection>

          <AggregationSection
            title="Agregaciones"
            description="Métricas calculadas por grupo (COUNT, SUM, AVG, MIN, MAX)."
            onAdd={addAggregation}
            addLabel="Agregar métrica"
          >
            {state.aggregations.length === 0 ? (
              <p className="text-xs text-gray-400 dark:text-gray-500">Sin agregaciones. Se requiere al menos una.</p>
            ) : (
              <div className="space-y-2">
                {state.aggregations.map((a, i) => (
                  <AggregationRow
                    key={i}
                    aggregation={a}
                    tables={tables}
                    useFields={useFields}
                    onChange={(patch) => updateAggregation(i, patch)}
                    onRemove={() => removeAggregation(i)}
                  />
                ))}
              </div>
            )}
          </AggregationSection>

          <AggregationSection
            title="Filtrar grupos (HAVING)"
            description={`Condiciones sobre las métricas, ej. ${copy.havingExampleMetric} > 1.`}
            onAdd={addHaving}
            addLabel="Agregar condición"
            disabled={metricOptions.length === 0}
          >
            {state.having.length === 0 ? (
              <p className="text-xs text-gray-400 dark:text-gray-500">Sin condiciones sobre los grupos.</p>
            ) : (
              <div className="space-y-2">
                {state.having.map((h, i) => (
                  <HavingRow
                    key={i}
                    having={h}
                    metricOptions={metricOptions}
                    onChange={(patch) => updateHaving(i, patch)}
                    onRemove={() => removeHaving(i)}
                  />
                ))}
              </div>
            )}
          </AggregationSection>

          <AggregationSection
            title="Ordenar por"
            description="Orden de los resultados agrupados."
            onAdd={addOrderBy}
            addLabel="Agregar orden"
            disabled={fieldOptions.length === 0}
          >
            {state.orderBy.length === 0 ? (
              <p className="text-xs text-gray-400 dark:text-gray-500">Sin orden definido.</p>
            ) : (
              <div className="space-y-2">
                {state.orderBy.map((o, i) => (
                  <OrderByRow
                    key={i}
                    order={o}
                    fieldOptions={fieldOptions}
                    onChange={(patch) => updateOrderBy(i, patch)}
                    onRemove={() => removeOrderBy(i)}
                  />
                ))}
              </div>
            )}
          </AggregationSection>
        </>
      )}
    </div>
  );
};
