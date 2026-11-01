import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { AlertTriangle, Upload } from "lucide-react";
import { PageMeta } from "@/ui/pages/page-meta";
import { ModuleBase } from "@/ui/components/common/module-base";
import { Card, CardTitle } from "@/ui/components/card";
import { Select } from "@/ui/components/inputs/select";
import { Input } from "@/ui/components/inputs/input";
import { Textarea } from "@/ui/components/inputs/textarea";
import { DropZone } from "@/ui/components/inputs/drop-zone";
import { Switch } from "@/ui/components/switch";
import { WizardForm } from "@/ui/components/wizard-form";
import { useOrgModule } from "@/companies/hooks/use-org-module";
import { useBreadcrumb } from "@/companies/hooks/use-breadcrumb";
import { usePortfolios } from "@/companies/hooks/use-portfolios";
import { useChannels } from "@/campaigns/hooks/use-channels";
import { useTemplates } from "@/templates/hooks/use-templates";
import { useBulkSend } from "@/bulk-send/hooks/use-bulk-send";
import { BULK_SEND_WIZARD_STEPS } from "@/bulk-send/constants/bulk-send-wizard-options";
import { BULK_SEND_ALLOWED_FILE_TYPES } from "@/bulk-send/constants/bulk-send-allowed-file-types";
import { ResultCard } from "@/bulk-send/components/result-card";

export const BulkSendPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const portfolioIdParam = searchParams.get("portfolio") ?? "";
  const { orgId } = useOrgModule();
  const { build } = useBreadcrumb();

  const { portfolios } = usePortfolios(orgId);
  const portfolioName = portfolios.find((p) => p.id === portfolioIdParam)?.name ?? "Portafolio";

  const [portfolioId, setPortfolioId] = useState(portfolioIdParam);

  const { channels } = useChannels();
  const { items: allTemplates } = useTemplates(portfolioId);
  const { send, sending, result, reset } = useBulkSend();

  const [channelId, setChannelId] = useState("");
  const [useTemplate, setUseTemplate] = useState(true);
  const [templateId, setTemplateId] = useState("");
  const [body, setBody] = useState("");
  const [subject, setSubject] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const selectedChannel = channels.find((c) => c.id === channelId);
  const channelName = selectedChannel?.name ?? "";
  const isEmail = channelName === "EMAIL";
  const isWhatsApp = channelName === "WHATSAPP";

  const compatibleTemplates = allTemplates.filter((t) => t.channel === channelName);

  useEffect(() => {
    if (templateId && !compatibleTemplates.some((t) => t.id === templateId)) {
      setTemplateId("");
    }
  }, [channelId]);

  useEffect(() => {
    if (isWhatsApp) setUseTemplate(true);
  }, [isWhatsApp]);

  useEffect(() => {
    if (!templateId) return;
    const tpl = allTemplates.find((t) => t.id === templateId);
    if (tpl?.subject) setSubject(tpl.subject);
  }, [templateId]);

  const selectedSubject = isEmail ? subject : undefined;
  const selectedTemplateId = useTemplate ? templateId : undefined;
  const selectedBody = !useTemplate ? body : undefined;

  const canAdvance = (step: number): boolean => {
    if (step === 0) return !!portfolioId && !!channelId;
    if (step === 1) return (useTemplate ? !!templateId : !!body.trim()) && (!isEmail || !!subject.trim());
    if (step === 2) return !!file;
    return true;
  };

  const canSubmit = !!file;
  const selectedTemplate = allTemplates.find((t) => t.id === templateId);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canAdvance(0) || !canAdvance(1) || !canSubmit) return;
    await send({
      portfolioId,
      channelId,
      templateId: selectedTemplateId,
      body: selectedBody,
      subject: selectedSubject,
      file: file!,
    });
  };

  const handleReset = () => {
    setChannelId("");
    setTemplateId("");
    setBody("");
    setSubject("");
    setFile(null);
    setUseTemplate(true);
    reset();
  };

  return (
    <>
      <PageMeta title="Envío masivo" description="Envía mensajes masivos desde un archivo CSV o Excel" />
      <ModuleBase
        pageTitle="Envío masivo"
        pageIcon={Upload}
        breadcrumbItems={build({
          portfolio: { id: portfolioIdParam, name: portfolioName },
          communications: true,
        })}
      >
        {result ? (
          <ResultCard result={result} onReset={handleReset} />
        ) : (
          <div className="mx-auto w-full max-w-2xl">
            <WizardForm
              steps={BULK_SEND_WIZARD_STEPS}
              canAdvance={canAdvance}
              canSubmit={canSubmit}
              onSubmit={handleSubmit}
              loading={sending}
              submitLabel="Confirmar y enviar"
              loadingLabel="Enviando..."
            >
              {(step) => (
                <>
                  {step === 0 && (
                    <Card className="w-full">
                      <CardTitle>Destino</CardTitle>
                      <div className="grid grid-cols-1 gap-5">
                        {!portfolioIdParam && (
                          <div>
                            <label className="mb-1.5 block text-sm font-medium text-gray-700 dark:text-gray-400">
                              Portafolio *
                            </label>
                            <Select
                              options={portfolios.map((p) => ({ value: p.id, label: p.name }))}
                              value={portfolioId}
                              onChange={setPortfolioId}
                              placeholder="Selecciona un portafolio"
                            />
                          </div>
                        )}

                        <div>
                          <label className="mb-1.5 block text-sm font-medium text-gray-700 dark:text-gray-400">
                            Canal *
                          </label>
                          <Select
                            options={channels.map((c) => ({ value: c.id, label: c.label }))}
                            value={channelId}
                            onChange={(v) => { setChannelId(v); setTemplateId(""); setBody(""); }}
                            placeholder="Selecciona un canal"
                          />
                        </div>

                        {channelId && !isWhatsApp && (
                          <div>
                            <Switch
                              checked={useTemplate}
                              onChange={(v) => { setUseTemplate(v); setTemplateId(""); setBody(""); }}
                              label="Usar plantilla guardada"
                            />
                          </div>
                        )}
                      </div>
                    </Card>
                  )}

                  {step === 1 && (
                    <Card className="w-full">
                      <CardTitle>Mensaje</CardTitle>
                      <div className="grid grid-cols-1 gap-5">
                        {useTemplate ? (
                          <div>
                            <label className="mb-1.5 block text-sm font-medium text-gray-700 dark:text-gray-400">
                              Plantilla *
                            </label>
                            <Select
                              options={compatibleTemplates.map((t) => ({ value: t.id, label: t.name }))}
                              value={templateId}
                              onChange={setTemplateId}
                              placeholder={compatibleTemplates.length === 0 ? "No hay plantillas para este canal" : "Selecciona una plantilla"}
                              disabled={compatibleTemplates.length === 0}
                            />
                          </div>
                        ) : (
                          <div>
                            <label className="mb-1.5 block text-sm font-medium text-gray-700 dark:text-gray-400">
                              Contenido del mensaje *
                              <span className="ml-1 font-normal text-gray-400">— usa {"{nombre_columna}"} para variables</span>
                            </label>
                            <Textarea
                              value={body}
                              onChange={(e) => setBody(e.target.value)}
                              rows={4}
                              placeholder="Hola {nombre}, tu saldo es {saldo}..."
                              className="resize-none"
                            />
                          </div>
                        )}

                        {isEmail && (
                          <div>
                            <Input
                              label="Asunto *"
                              id="bulk-subject"
                              value={subject}
                              onChange={(e) => setSubject(e.target.value)}
                              placeholder="Ej: Recordatorio de pago — {nombre}"
                            />
                          </div>
                        )}
                      </div>
                    </Card>
                  )}

                  {step === 2 && (
                    <Card className="w-full">
                      <CardTitle>Archivo de destinatarios</CardTitle>
                      <p className="text-sm text-gray-500 dark:text-gray-400 -mt-1">
                        El archivo debe tener las columnas <code className="text-brand-500">tipo_documento</code>, <code className="text-brand-500">documento</code> y <code className="text-brand-500">destinatario</code>. Las columnas adicionales se usan como variables en el mensaje.
                      </p>
                      <DropZone
                        label="Archivo CSV o Excel"
                        file={file}
                        onChange={(f) => setFile(f)}
                        allowed={BULK_SEND_ALLOWED_FILE_TYPES}
                        hint="CSV o XLSX · máx. 10 MB · 10 000 filas"
                      />
                    </Card>
                  )}

                  {step === 3 && (
                    <Card className="w-full">
                      <CardTitle>Confirma antes de enviar</CardTitle>
                      <dl className="grid grid-cols-1 gap-3 text-sm">
                        <div className="flex justify-between gap-4 border-b border-gray-100 pb-2 dark:border-white/5">
                          <dt className="text-gray-500 dark:text-gray-400">Portafolio</dt>
                          <dd className="font-medium text-gray-800 dark:text-white/90 text-right">{portfolioName}</dd>
                        </div>
                        <div className="flex justify-between gap-4 border-b border-gray-100 pb-2 dark:border-white/5">
                          <dt className="text-gray-500 dark:text-gray-400">Canal</dt>
                          <dd className="font-medium text-gray-800 dark:text-white/90 text-right">{selectedChannel?.label ?? "—"}</dd>
                        </div>
                        <div className="flex justify-between gap-4 border-b border-gray-100 pb-2 dark:border-white/5">
                          <dt className="text-gray-500 dark:text-gray-400">{useTemplate ? "Plantilla" : "Mensaje"}</dt>
                          <dd className="font-medium text-gray-800 dark:text-white/90 text-right truncate max-w-[60%]">
                            {useTemplate ? (selectedTemplate?.name ?? "—") : body}
                          </dd>
                        </div>
                        {isEmail && (
                          <div className="flex justify-between gap-4 border-b border-gray-100 pb-2 dark:border-white/5">
                            <dt className="text-gray-500 dark:text-gray-400">Asunto</dt>
                            <dd className="font-medium text-gray-800 dark:text-white/90 text-right truncate max-w-[60%]">{subject}</dd>
                          </div>
                        )}
                        <div className="flex justify-between gap-4 pb-1">
                          <dt className="text-gray-500 dark:text-gray-400">Archivo</dt>
                          <dd className="font-medium text-gray-800 dark:text-white/90 text-right truncate max-w-[60%]">{file?.name ?? "—"}</dd>
                        </div>
                      </dl>

                      <div className="mt-4 flex items-start gap-2 rounded-lg bg-warning-50 px-3 py-2.5 text-sm text-warning-700 dark:bg-warning-500/15 dark:text-warning-400">
                        <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                        <p>
                          Se enviará el mensaje a cada destinatario válido del archivo. Esta acción no se puede
                          deshacer una vez confirmada.
                        </p>
                      </div>
                    </Card>
                  )}
                </>
              )}
            </WizardForm>
          </div>
        )}
      </ModuleBase>
    </>
  );
};
