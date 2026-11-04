import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { ReactFlowProvider } from "@xyflow/react";
import { Phone, PhoneCall, Save, Send, Keyboard, CheckCircle2, AlertTriangle, Settings2, ListChecks } from "lucide-react";
import { PageMeta } from "@/ui/pages/page-meta";
import { Breadcrumb } from "@/ui/components/common/breadcrumb";
import { Input } from "@/ui/components/inputs/input";
import { Button } from "@/ui/components/button/button";
import { useOrgModule } from "@/companies/hooks/use-org-module";
import { useBreadcrumb } from "@/companies/hooks/use-breadcrumb";
import { usePortfolios } from "@/companies/hooks/use-portfolios";
import { useIvrFlow } from "@/ivr/hooks/use-ivr-flow";
import { useSaveFlow } from "@/ivr/hooks/use-save-flow";
import { useTestCall } from "@/ivr/hooks/use-test-call";
import { useIvrShortcuts } from "@/ivr/hooks/use-ivr-shortcuts";
import { IvrEditorContext, type IvrEditorContextValue } from "@/ivr/contexts/ivr-editor-context";
import { IvrCanvas } from "@/ivr/components/ivr-canvas";
import { IvrNodeSidebar } from "@/ivr/components/ivr-node-sidebar";
import { AudioLibraryModal } from "@/ivr/components/audio-library-modal";
import { FlowSettingsPanel } from "@/ivr/components/flow-settings-panel";
import { OutcomesPanel } from "@/ivr/components/outcomes-panel";
import { TestCallModal, type TestCallFormData } from "@/ivr/components/test-call-modal";
import { ShortcutsPanel } from "@/ivr/components/shortcuts-panel";
import type { IvrNode, IvrEdge } from "@/ivr/types/ivr-node-types";
import type { IvrAudio } from "@/ivr/types/ivr-audio-types";

/**
 * Diseñador visual de flujos IVR (canal CALL de campañas masivas). Página full
 * screen: barra de herramientas + panel lateral de nodos + lienzo React Flow.
 * Guarda contra la API real (`/ivr/flows`); la campaña se crea desde el wizard
 * seleccionando el flujo guardado. Con `?flowId=` edita un flujo existente.
 */
export const IvrDesignerPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const portfolioId = searchParams.get("portfolio") ?? "";
  const flowIdParam = searchParams.get("flowId");
  const { orgId } = useOrgModule();
  const { build } = useBreadcrumb();

  const { portfolios } = usePortfolios(orgId);
  const portfolioName = portfolios.find((p) => p.id === portfolioId)?.name ?? "Portafolio";

  const flow = useIvrFlow();
  const { saving, loadFlow, saveFlow } = useSaveFlow(portfolioId);
  const { sending: testing, sendTestCall } = useTestCall();

  const [backendId, setBackendId] = useState<string | null>(null);
  const [flowName, setFlowName] = useState("Flujo IVR sin título");
  const [audioOpen, setAudioOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [outcomesOpen, setOutcomesOpen] = useState(false);
  const [testOpen, setTestOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const audioSelect = useRef<((audio: IvrAudio) => void) | null>(null);

  // Carga el flujo existente cuando se abre con ?flowId= (desde el wizard).
  useEffect(() => {
    if (!flowIdParam) return;
    loadFlow(flowIdParam).then((rec) => {
      if (!rec) return;
      setBackendId(rec.id);
      setFlowName(rec.name);
      if (rec.graph) {
        flow.hydrate({
          nodes: rec.graph.nodes as unknown as IvrNode[],
          edges: rec.graph.edges as unknown as IvrEdge[],
          entryNodeId: rec.graph.entryNodeId,
          defaults: rec.graph.defaults,
          redial: rec.graph.redial,
          amdPreset: rec.graph.amdPreset,
          amd: rec.graph.amd,
          outcomes: rec.graph.outcomes,
          pacing: {
            callsPerSecond: rec.callsPerSecond ?? null,
            maxConcurrent: rec.maxConcurrent ?? null,
            callerId: rec.callerId ?? "",
            contactPolicyId: rec.contactPolicyId ?? "",
          },
        });
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flowIdParam]);

  useIvrShortcuts({
    onDuplicate: flow.duplicateSelection,
    onUndo: flow.undo,
    onRedo: flow.redo,
    onSelectAll: flow.selectAll,
  });

  const editorValue: IvrEditorContextValue = useMemo(
    () => ({
      updateNodeData: flow.updateNodeData,
      takeSnapshot: flow.takeSnapshot,
      removeHandleEdges: flow.removeHandleEdges,
      openAudioLibrary: (onSelect) => {
        audioSelect.current = onSelect;
        setAudioOpen(true);
      },
      entryNodeId: flow.entryNodeId,
      setEntryNode: flow.setEntryNode,
    }),
    [flow.updateNodeData, flow.takeSnapshot, flow.removeHandleEdges, flow.entryNodeId, flow.setEntryNode],
  );

  const handleSave = async () => {
    const res = await saveFlow({
      backendId,
      name: flowName,
      nodes: flow.nodes,
      edges: flow.edges,
      entryNodeId: flow.entryNodeId,
      defaults: flow.defaults,
      redial: flow.redial,
      amdPreset: flow.amdPreset,
      amd: flow.amd,
      outcomes: flow.outcomes,
      pacing: flow.pacing,
    });
    setWarnings(res.warnings);
    if (!res.ok) {
      setErrors(res.errors);
      setSavedAt(null);
      return;
    }
    setErrors([]);
    if (res.flow) setBackendId(res.flow.id);
    setSavedAt(new Date());
  };

  const handleTestCall = (data: TestCallFormData) =>
    sendTestCall({
      nodes: flow.nodes,
      edges: flow.edges,
      entryNodeId: flow.entryNodeId,
      defaults: flow.defaults,
      redial: flow.redial,
      amd: flow.amd,
      phone: data.phone,
      portfolioId,
      customerName: data.customerName,
      customerDocument: data.customerDocument,
    });

  const breadcrumbItems = build({
    portfolio: { id: portfolioId, name: portfolioName },
    communications: true,
    trail: [{ label: "Campañas", path: undefined, icon: Send }],
  });

  return (
    <>
      <PageMeta title="Diseñador IVR" description="Diseñador visual de flujos de llamada IVR" />
      <div className="flex flex-1 min-h-0 flex-col overflow-hidden">
        <Breadcrumb pageTitle="Diseñador IVR" pageIcon={Phone} items={breadcrumbItems} />

        <div className="flex flex-1 min-h-0 flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-gray-800 dark:bg-white/3">
          {/* Barra de herramientas */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 p-3 dark:border-gray-800">
            <div className="flex items-center gap-2">
              <Phone size={18} className="text-brand-500" />
              <Input
                value={flowName}
                onChange={(e) => setFlowName(e.target.value)}
                placeholder="Nombre del flujo"
                className="h-9! w-64 py-1.5!"
              />
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                startIcon={<Settings2 size={15} />}
                onClick={() => setSettingsOpen(true)}
                className="py-2!"
              >
                Ajustes
              </Button>
              <Button
                size="sm"
                variant="outline"
                startIcon={<ListChecks size={15} />}
                onClick={() => setOutcomesOpen(true)}
                className="py-2!"
              >
                Resultados
              </Button>
              <Button
                size="sm"
                variant="outline"
                startIcon={<PhoneCall size={15} />}
                onClick={() => setTestOpen(true)}
                className="py-2!"
              >
                Probar
              </Button>
              <Button
                size="sm"
                variant="primary"
                startIcon={<Save size={15} />}
                onClick={handleSave}
                disabled={saving}
                className="py-2!"
              >
                {saving ? "Guardando…" : "Guardar flujo"}
              </Button>
              <button
                type="button"
                onClick={() => setShortcutsOpen(true)}
                className="flex h-9 w-9 items-center justify-center rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-400 dark:hover:bg-white/5"
                title="Atajos de teclado"
              >
                <Keyboard size={16} />
              </button>
            </div>
          </div>

          {/* Feedback de guardado / errores de validación */}
          {savedAt && errors.length === 0 && (
            <div className="flex items-center gap-2 border-b border-gray-100 bg-success-50 px-3 py-2 text-xs text-success-700 dark:border-gray-800 dark:bg-success-500/10 dark:text-success-300">
              <CheckCircle2 size={14} />
              Flujo guardado a las {savedAt.toLocaleTimeString()}.
            </div>
          )}
          {errors.length > 0 && (
            <div className="border-b border-gray-100 bg-error-50 px-3 py-2 text-xs text-error-700 dark:border-gray-800 dark:bg-error-500/10 dark:text-error-300">
              <div className="mb-1 flex items-center gap-2 font-medium">
                <AlertTriangle size={14} />
                Corrige estos puntos antes de guardar:
              </div>
              <ul className="ml-6 list-disc space-y-0.5">
                {errors.map((err, i) => (
                  <li key={i}>{err}</li>
                ))}
              </ul>
            </div>
          )}
          {warnings.length > 0 && errors.length === 0 && (
            <div className="border-b border-gray-100 bg-warning-50 px-3 py-2 text-xs text-warning-700 dark:border-gray-800 dark:bg-warning-500/10 dark:text-warning-300">
              <div className="mb-1 flex items-center gap-2 font-medium">
                <AlertTriangle size={14} />
                El flujo se guardó, pero revisa esto:
              </div>
              <ul className="ml-6 list-disc space-y-0.5">
                {warnings.map((warn, i) => (
                  <li key={i}>{warn}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Editor: panel lateral + lienzo */}
          <ReactFlowProvider>
            <IvrEditorContext.Provider value={editorValue}>
              <div className="flex flex-1 min-h-0">
                <IvrNodeSidebar onAdd={(type) => flow.addNode(type)} />
                <div className="relative h-full flex-1">
                  <IvrCanvas
                    nodes={flow.nodes}
                    edges={flow.edges}
                    onNodesChange={flow.onNodesChange}
                    onEdgesChange={flow.onEdgesChange}
                    onConnect={flow.onConnect}
                    onAddNodeAt={flow.addNode}
                    onNodeDragStart={flow.takeSnapshot}
                  />
                </div>
              </div>
            </IvrEditorContext.Provider>
          </ReactFlowProvider>
        </div>
      </div>

      <AudioLibraryModal
        isOpen={audioOpen}
        onClose={() => setAudioOpen(false)}
        onSelect={(audio) => {
          audioSelect.current?.(audio);
          setAudioOpen(false);
        }}
      />
      <FlowSettingsPanel
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        defaults={flow.defaults}
        redial={flow.redial}
        pacing={flow.pacing}
        amdPreset={flow.amdPreset}
        amd={flow.amd}
        onDefaultsChange={flow.setDefaults}
        onRedialChange={flow.setRedial}
        onPacingChange={flow.setPacing}
        onAmdPresetChange={flow.applyAmdPreset}
        onAmdVariableChange={flow.setAmdVariable}
      />
      <OutcomesPanel
        isOpen={outcomesOpen}
        onClose={() => setOutcomesOpen(false)}
        nodes={flow.nodes}
        outcomes={flow.outcomes}
        onChange={flow.setOutcomeLabel}
      />
      <TestCallModal
        isOpen={testOpen}
        onClose={() => setTestOpen(false)}
        onCall={handleTestCall}
        sending={testing}
      />
      <ShortcutsPanel isOpen={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
    </>
  );
};
