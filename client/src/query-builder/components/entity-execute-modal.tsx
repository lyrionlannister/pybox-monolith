import { useState } from "react";
import { Play } from "lucide-react";
import { Modal } from "@/ui/components/modal/modal";
import { Loader } from "@/ui/components/loader/loader";
import { Spinner } from "@/ui/components/loader/spinner";
import { EntityResultsTable } from "./entity-results-table";
import { useEntityExecute } from "@/hooks/use-entity-execution";
import type { EntityExecuteResponse } from "@/query-builder/types/query-builder-types";
import type { EntityExecuteModalProps } from "@/query-builder/types/entity-execute-modal-props";

export const EntityExecuteModal: React.FC<EntityExecuteModalProps> = ({
  config,
  isOpen,
  onClose,
  entity,
  scopeId,
}) => {
  const { executing, result, jobAccepted, execute, clearResult } = useEntityExecute<EntityExecuteResponse>(config.kind, scopeId);
  const [mode, setMode] = useState<"preview" | "audit">("preview");
  const [limit, setLimit] = useState("100");

  const handleClose = () => {
    clearResult();
    onClose();
  };

  const handleExecute = () => {
    const lim = parseInt(limit);
    execute(entity.id, mode, isNaN(lim) || lim <= 0 ? undefined : lim);
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      className={`mx-4 flex max-h-[90vh] w-full flex-col p-6 ${result ? "max-w-[95vw]" : "max-w-4xl"}`}
    >
      <h2 className="mb-1 text-lg font-semibold text-gray-800 dark:text-white">
        Ejecutar — {entity.name}
      </h2>
      <p className="mb-5 text-sm text-gray-500 dark:text-gray-400">
        <strong>Preview</strong> muestra datos sin guardar. <strong>Audit</strong> genera un CSV y registra la ejecución.
      </p>

      {!result && (
        <div className="space-y-4">
          <div className="flex gap-3">
            {(["preview", "audit"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={`flex-1 rounded-xl border-2 py-3 text-sm font-medium transition-colors ${
                  mode === m
                    ? "border-brand-500 bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-400"
                    : "border-gray-200 bg-white text-gray-600 hover:border-gray-300 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-400"
                }`}
              >
                {m === "preview" ? "Preview" : "Audit (genera CSV)"}
              </button>
            ))}
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
              Límite de filas
            </label>
            <input
              type="number"
              min={1}
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 outline-none transition focus:border-brand-500 focus:ring-1 focus:ring-brand-500 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300"
            />
          </div>

          <button
            type="button"
            onClick={handleExecute}
            disabled={executing}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-brand-500 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-600 disabled:opacity-50"
          >
            {executing ? <Spinner size="xs" tone="current" /> : <Play size={16} />}
            Ejecutar
          </button>
        </div>
      )}

      {executing && (
        <div className="py-12">
          <Loader />
        </div>
      )}

      {jobAccepted && !executing && (
        <div className="flex flex-col items-center gap-4 py-12 text-center">
          <p className="text-sm text-gray-600 dark:text-gray-400">
            Tu reporte se está generando. Recibirás una notificación cuando el archivo esté listo.
          </p>
          <button
            type="button"
            onClick={handleClose}
            className="text-sm text-brand-500 hover:underline"
          >
            Cerrar
          </button>
        </div>
      )}

      {result && !executing && (
        <div className="flex min-h-0 flex-1 flex-col gap-4">
          <EntityResultsTable result={result} config={config} />
          <button
            type="button"
            onClick={clearResult}
            className="shrink-0 text-sm text-brand-500 hover:underline"
          >
            ← Volver a configurar
          </button>
        </div>
      )}
    </Modal>
  );
};
