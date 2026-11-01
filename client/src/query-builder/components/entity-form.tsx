import { ChevronLeft } from "lucide-react";
import { StepIndicator } from "@/ui/components/step-indicator";
import { Spinner } from "@/ui/components/loader/spinner";
import { StepBasicInfo } from "./step-basic-info";
import { StepTablesFilters } from "./step-tables-filters";
import { StepJoins } from "./step-joins";
import { StepAggregation } from "./step-aggregation";
import { StepSummary } from "./step-summary";
import { useEntityForm } from "@/query-builder/hooks/use-entity-form";
import type { EntityFormProps } from "@/query-builder/types/entity-form-props";

export const EntityForm: React.FC<EntityFormProps> = ({
  config,
  scopeId,
  onSuccess,
  onCancel,
  existing,
}) => {
  const {
    step,
    state,
    update,
    submitting,
    nextStep,
    prevStep,
    addTable,
    removeTable,
    updateTable,
    addJoin,
    removeJoin,
    updateJoin,
    submit,
    allTableAliases,
  } = useEntityForm(config.kind, config.configKey, config.steps.length, scopeId, onSuccess, existing);

  const isLastStep = step === config.steps.length - 1;

  const canNext = () => {
    if (step === 0) return !!state.name.trim() && !!state.mainTable;
    if (step === 3 && state.aggregateMode) {
      return state.aggregations.length > 0 && state.aggregations.every((a) => !!a.column && !!a.alias);
    }
    return true;
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={step === 0 ? onCancel : prevStep}
          className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm text-gray-500 transition hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
        >
          <ChevronLeft size={16} />
          {step === 0 ? "Cancelar" : "Atrás"}
        </button>
        <h2 className="text-base font-semibold text-gray-800 dark:text-white">
          {existing ? `Editar ${config.copy.entityNoun}` : `Nuevo ${config.copy.entityNoun}`} — {config.steps[step]}
        </h2>
      </div>

      <StepIndicator current={step} total={config.steps.length} />

      <div>
        {step === 0 && <StepBasicInfo state={state} update={update} config={config} />}
        {step === 1 && (
          <StepTablesFilters
            state={state}
            update={update}
            addTable={addTable}
            removeTable={removeTable}
            updateTable={updateTable}
            config={config}
          />
        )}
        {step === 2 && (
          <StepJoins
            state={state}
            addJoin={addJoin}
            removeJoin={removeJoin}
            updateJoin={updateJoin}
            allTableAliases={allTableAliases}
          />
        )}
        {step === 3 && <StepAggregation state={state} update={update} config={config} />}
        {step === 4 && <StepSummary state={state} config={config} />}
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-gray-100 pt-4 dark:border-gray-800">
        {step > 0 ? (
          <button
            type="button"
            onClick={prevStep}
            className="flex items-center gap-1.5 rounded-xl border border-gray-200 px-5 py-2.5 text-sm font-semibold text-gray-700 transition hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
          >
            <ChevronLeft size={16} />
            Anterior
          </button>
        ) : (
          <span />
        )}
        {isLastStep ? (
          <button
            type="button"
            onClick={submit}
            disabled={submitting}
            className="flex items-center justify-center gap-2 rounded-xl bg-brand-500 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-600 disabled:opacity-50"
          >
            {submitting && <Spinner size="xs" tone="current" />}
            {existing ? "Guardar cambios" : `Crear ${config.copy.entityNoun}`}
          </button>
        ) : (
          <button
            type="button"
            onClick={nextStep}
            disabled={!canNext()}
            className="rounded-xl bg-brand-500 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-600 disabled:opacity-40"
          >
            Siguiente
          </button>
        )}
      </div>
    </div>
  );
};
