import { useEntityList } from "@/query-builder/hooks/use-entity-list";
import { REPORT_QUERY_BUILDER_CONFIG as CONFIG } from "@/reports/constants/report-query-builder-config";

/**
 * El módulo reports no tiene fetch propio: reutiliza el contrato de listado
 * compartido con segments (useEntityList) para no duplicar la lógica de
 * paginación/borrado. Este hook solo fija la config de reports para que la
 * página consuma un hook de su propio módulo en vez de fetch/CONFIG inline.
 */
export const useReports = (orgId: string) => useEntityList(CONFIG.kind, CONFIG.configKey, orgId);
