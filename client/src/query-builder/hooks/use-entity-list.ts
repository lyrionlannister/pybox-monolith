import { useCallback, useEffect, useState } from "react";
import { useApiClient } from "@/hooks/use-api-client";
import type { EntityResponse } from "@/query-builder/types/query-builder-types";

const PAGE_SIZE = 20;

interface RawEntityResponse {
  id: string;
  name: string;
  description: string | null;
  organizationId: string;
  [key: string]: unknown;
}

/**
 * Compartido por segments y reports: ambos exponen el mismo contrato de listado,
 * solo cambia el segmento de URL (kind) y el nombre del campo con la config de la
 * query dentro de cada item (configKey: filterCriteria | reportConfig).
 */
export const useEntityList = (
  kind: "segments" | "reports",
  configKey: "filterCriteria" | "reportConfig",
  id: string,
) => {
  const { apiClient } = useApiClient();
  const [entities, setEntities] = useState<EntityResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  const paramName = kind === "segments" ? "portfolioId" : "organizationId";

  const fetchPage = useCallback((p: number) => {
    if (!id) { setLoading(false); return; }
    setLoading(true);
    const params = new URLSearchParams({
      [paramName]: id,
      page: String(p),
      pageSize: String(PAGE_SIZE),
    });
    apiClient(`/${kind}/?${params}`)
      .then((data: { items: RawEntityResponse[]; total: number }) => {
        const items: EntityResponse[] = (data.items ?? []).map((raw) => ({
          id: raw.id,
          name: raw.name,
          description: raw.description,
          organizationId: raw.organizationId,
          config: (raw[configKey] as Record<string, unknown>) ?? {},
        }));
        setEntities(items);
        setTotal(data.total ?? 0);
      })
      .catch(() => {
        setEntities([]);
        setTotal(0);
      })
      .finally(() => setLoading(false));
  }, [id, apiClient, kind, configKey, paramName]);

  useEffect(() => {
    setPage(1);
    fetchPage(1);
  }, [fetchPage]);

  const goToPage = (p: number) => {
    setPage(p);
    fetchPage(p);
  };

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const deleteEntity = async (entityId: string) => {
    await apiClient(`/${kind}/${entityId}?${paramName}=${id}`, { method: "DELETE" });
    const targetPage = entities.length === 1 && page > 1 ? page - 1 : page;
    setPage(targetPage);
    fetchPage(targetPage);
  };

  return {
    entities, total, page, pages, loading,
    refetch: () => fetchPage(page), goToPage,
    deleteEntity,
  };
};
