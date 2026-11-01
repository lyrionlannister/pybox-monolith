import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { useApiClient } from "@/hooks/use-api-client";
import { useToast } from "@/context/toast-context";
import { useSchemas } from "@/databases/hooks/use-schemas";
import { useSchemaTables } from "@/databases/hooks/use-schema-tables";
import { useTableFields } from "@/databases/hooks/use-table-fields";
import { emptyColumnDefinition } from "@/databases/constants/column-data-type-options";
import type { AlterTableFormState } from "@/databases/types/alter-table-form-state";
import type { OperationResponse } from "@/databases/types/database-types";

/**
 * Encapsula el estado del wizard de alteración de tabla (esquemas/tablas/
 * columnas disponibles, validación por paso y el submit al backend) para que
 * alter-table-page.tsx quede solo como orquestación.
 */
export const useAlterTable = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { apiClient } = useApiClient();
  const { success, error } = useToast();

  const { schemas } = useSchemas();

  const [form, setForm] = useState<AlterTableFormState>({
    schema: searchParams.get("schema") || "public",
    table: searchParams.get("table") || "",
    action: "ADD_COLUMN",
    addColumn: emptyColumnDefinition(),
    dropColumnName: "",
    modifyColumnName: "",
    modifyColumn: emptyColumnDefinition(),
    renameColumnName: "",
    newColumnName: "",
  });
  const [saving, setSaving] = useState(false);

  const { tables } = useSchemaTables(form.schema);
  const { fields } = useTableFields(form.schema, form.table);

  const set = <K extends keyof AlterTableFormState>(key: K) =>
    (value: AlterTableFormState[K]) =>
      setForm((prev) => ({ ...prev, [key]: value }));

  const targetValid = form.schema.trim() !== "" && form.table.trim() !== "";
  const changeValid =
    form.action === "ADD_COLUMN"
      ? form.addColumn.name.trim() !== ""
      : form.action === "DROP_COLUMN"
        ? form.dropColumnName !== ""
        : form.action === "MODIFY_COLUMN"
          ? form.modifyColumnName !== ""
          : form.renameColumnName !== "" && form.newColumnName.trim() !== "";

  const canAdvance = (step: number) => {
    if (step === 0) return targetValid;
    if (step === 1) return changeValid;
    return true;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);

    const body =
      form.action === "ADD_COLUMN"
        ? {
            action: form.action,
            column: { ...form.addColumn, defaultValue: form.addColumn.defaultValue || null },
            columnName: null,
            newColumnName: null,
          }
        : form.action === "DROP_COLUMN"
          ? { action: form.action, column: null, columnName: form.dropColumnName, newColumnName: null }
          : form.action === "MODIFY_COLUMN"
            ? {
                action: form.action,
                column: { ...form.modifyColumn, defaultValue: form.modifyColumn.defaultValue || null },
                columnName: form.modifyColumnName,
                newColumnName: null,
              }
            : { action: form.action, column: null, columnName: form.renameColumnName, newColumnName: form.newColumnName.trim() };

    try {
      const result = await apiClient<OperationResponse>(`/databases/schemas/${form.schema}/tables/${form.table}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      if (!result?.success) {
        error("No se pudo alterar la tabla", result?.message);
        return;
      }
      success("Tabla alterada", result.message);
      navigate("/databases");
    } finally {
      setSaving(false);
    }
  };

  return {
    schemas,
    tables,
    fields,
    form,
    set,
    saving,
    targetValid,
    changeValid,
    canAdvance,
    handleSubmit,
  };
};
