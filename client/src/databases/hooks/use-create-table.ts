import { useState } from "react";
import { useNavigate } from "react-router";
import { useApiClient } from "@/hooks/use-api-client";
import { useToast } from "@/context/toast-context";
import { useSchemas } from "@/databases/hooks/use-schemas";
import type { ColumnDefinition, OperationResponse } from "@/databases/types/database-types";

/**
 * Encapsula el estado del wizard de creación de tabla (esquemas disponibles,
 * columnas, validación por paso y el submit al backend) para que
 * create-table-page.tsx quede solo como orquestación.
 */
export const useCreateTable = () => {
  const navigate = useNavigate();
  const { apiClient } = useApiClient();
  const { success, error } = useToast();
  const { schemas, loading: loadingSchemas } = useSchemas();

  const [schema, setSchema] = useState("public");
  const [tableName, setTableName] = useState("");
  const [columns, setColumns] = useState<ColumnDefinition[]>([]);
  const [saving, setSaving] = useState(false);

  const locationValid = schema.trim() !== "" && tableName.trim() !== "";
  const columnsValid = columns.length > 0 && columns.every((c) => c.name.trim() !== "");

  const canAdvance = (step: number) => {
    if (step === 0) return locationValid;
    if (step === 1) return columnsValid;
    return true;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const result = await apiClient<OperationResponse>(`/databases/schemas/${schema}/tables`, {
        method: "POST",
        body: JSON.stringify({
          tableName: tableName.trim(),
          columns: columns.map((c) => ({ ...c, defaultValue: c.defaultValue || null })),
        }),
      });
      if (!result?.success) {
        error("No se pudo crear la tabla", result?.message);
        return;
      }
      success("Tabla creada", result.message);
      navigate("/databases");
    } finally {
      setSaving(false);
    }
  };

  return {
    schemas,
    loadingSchemas,
    schema,
    setSchema,
    tableName,
    setTableName,
    columns,
    setColumns,
    saving,
    locationValid,
    columnsValid,
    canAdvance,
    handleSubmit,
  };
};
