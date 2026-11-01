import type { CampaignStatus, Periodicity } from "@/types/campaigns/campaign-types";

export const CAMPAIGN_PERIODICITY_LABELS: Record<Periodicity, string> = {
  UNA_VEZ: "Única vez",
  INMEDIATO: "Inmediata",
  DIARIO: "Diaria",
  SEMANAL: "Semanal",
  MENSUAL: "Mensual",
};

/** Solo estas campañas admiten reprogramación desde el calendario. */
export const CAMPAIGN_EDITABLE_STATUSES: CampaignStatus[] = ["PROGRAMADA", "PAUSADA"];

export interface CampaignStatusMeta {
  label: string;
  eventColor: string;
  eventTextColor: string;
  chipClass: string;
}

export const CAMPAIGN_STATUS_META: Record<CampaignStatus, CampaignStatusMeta> = {
  "BORRADOR": { label: "Borrador", eventColor: "#e5e7eb", eventTextColor: "#374151", chipClass: "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400" },
  "PROGRAMADA": { label: "Programada", eventColor: "#465fff", eventTextColor: "#ffffff", chipClass: "bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-400" },
  "EN_EJECUCION": { label: "En ejecución", eventColor: "#f79009", eventTextColor: "#ffffff", chipClass: "bg-warning-50 text-warning-700 dark:bg-warning-500/15 dark:text-orange-400" },
  "COMPLETADA": { label: "Completada", eventColor: "#12b76a", eventTextColor: "#ffffff", chipClass: "bg-success-50 text-success-700 dark:bg-success-500/10 dark:text-success-400" },
  "FALLIDA": { label: "Fallida", eventColor: "#f04438", eventTextColor: "#ffffff", chipClass: "bg-error-50 text-error-600 dark:bg-error-500/10 dark:text-error-400" },
  "PAUSADA": { label: "Pausada", eventColor: "#fb6514", eventTextColor: "#ffffff", chipClass: "bg-orange-50 text-orange-700 dark:bg-orange-500/15 dark:text-orange-400" },
  "CANCELADA": { label: "Cancelada", eventColor: "#d1d5db", eventTextColor: "#4b5563", chipClass: "bg-gray-200 text-gray-600 dark:bg-white/5 dark:text-gray-500" },
};
