import type { IvrFlowSerialized, IvrOutcomeMap } from "./ivr-node-types";
import type { CampaignIvrConfig, CampaignRedialConfig } from "@/ivr/utils/compile-flow";

/** Flujo IVR tal como lo devuelve el backend (`/ivr/flows`). */
export type IvrFlowRecord = {
  id: string;
  name: string;
  description?: string | null;
  /** CampaignIvrConfig compilado (listo para Helena). */
  config: CampaignIvrConfig;
  /** Grafo crudo de React Flow para reeditar en el diseñador. */
  graph: IvrFlowSerialized | null;
  redialConfig?: CampaignRedialConfig | null;
  /** Variables por defecto para Helena (AMD_*, PJSIP_TRUNK, …). */
  variables?: Record<string, string> | null;
  /** Etiquetas de resultado compiladas, indexadas por nombre de nodo en Helena. */
  outcomes?: IvrOutcomeMap | null;
  /** Ritmo de marcación y caller ID por defecto del flujo. */
  callsPerSecond?: number | null;
  maxConcurrent?: number | null;
  callerId?: string | null;
  contactPolicyId?: string | null;
  createdAt: string;
  updatedAt?: string | null;
};

/** Resumen de flujo para selectores (wizard de campaña). */
export type IvrFlowSummary = {
  id: string;
  name: string;
};
