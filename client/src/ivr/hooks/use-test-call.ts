import { useCallback, useState } from "react";
import { useApiClient } from "@/hooks/use-api-client";
import type { IvrNode, IvrEdge, IvrDefaults, IvrRedial } from "@/ivr/types/ivr-node-types";
import type { AmdVariables } from "@/ivr/constants/amd-presets";
import { compileFlow } from "@/ivr/utils/compile-flow";

export type TestCallParams = {
  nodes: IvrNode[];
  edges: IvrEdge[];
  entryNodeId: string | null;
  defaults: IvrDefaults;
  redial: IvrRedial;
  amd: AmdVariables;
  phone: string;
  portfolioId: string;
  customerName?: string;
  customerDocument?: string;
};

export type TestCallResult = { ok: boolean; errors: string[] };

/**
 * Envía una llamada de prueba del flujo actual a un número dado. Compila el
 * grafo (bloquea si hay errores) y postea a `/ivr/test-call` con el config +
 * las variables AMD; Helena marca ese único número.
 */
export const useTestCall = () => {
  const { apiClient } = useApiClient();
  const [sending, setSending] = useState(false);

  const sendTestCall = useCallback(
    async (params: TestCallParams): Promise<TestCallResult> => {
      const { errors, config, redialConfig } = compileFlow({
        nodes: params.nodes,
        edges: params.edges,
        entryNodeId: params.entryNodeId,
        defaults: params.defaults,
        redial: params.redial,
      });
      if (errors.length > 0 || !config) return { ok: false, errors };

      setSending(true);
      try {
        await apiClient("/ivr/test-call/", {
          method: "POST",
          body: JSON.stringify({
            phone: params.phone,
            portfolioId: params.portfolioId,
            config,
            variables: params.amd,
            customerName: params.customerName || null,
            customerDocument: params.customerDocument || null,
            redialConfig,
          }),
        });
        return { ok: true, errors: [] };
      } catch {
        // apiClient ya muestra un toast con el detalle del error.
        return { ok: false, errors: [] };
      } finally {
        setSending(false);
      }
    },
    [apiClient],
  );

  return { sending, sendTestCall };
};
