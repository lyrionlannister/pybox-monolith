import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { useApiClient } from "@/hooks/use-api-client";
import { useCountries } from "@/hooks/use-countries";
import { useToast } from "@/context/toast-context";
import { useOrgModule } from "@/companies/hooks/use-org-module";
import { usePortfolios } from "@/companies/hooks/use-portfolios";
import { useSegmentOptions } from "@/segments/hooks/use-segment-options";
import { useTemplateOptions } from "@/templates/hooks/use-template-options";
import { useTemplateVariables } from "@/templates/hooks/use-template-variables";
import { useChannels } from "@/campaigns/hooks/use-channels";
import { useCampaignPeriodicities } from "@/campaigns/hooks/use-campaign-periodicities";
import { useCampaignWeekdays } from "@/campaigns/hooks/use-campaign-weekdays";
import { useIvrFlows } from "@/ivr/hooks/use-ivr-flows";
import type { Campaign } from "@/types/campaigns/campaign-types";
import type {
  CampaignEditorFormState,
  CampaignFrequency,
  RecurringPeriodicity,
} from "@/campaigns/types/campaign-editor-form-state";

const EMPTY: CampaignEditorFormState = {
  name: "",
  description: "",
  channelId: "",
  segmentId: "",
  templateId: "",
  ivrFlowId: "",
  message: "",
  subject: "",
  fallback: true,
  timezone: "UTC",
  frequency: "INMEDIATO",
  recurringPeriodicity: "SEMANAL",
  scheduledAt: "",
  timeToSend: "",
  daysOfWeek: [],
  dayOfMonth: null,
};

/**
 * Encapsula todo el estado/side-effects del wizard de campañas (carga de la
 * campaña en edición, catálogos relacionados, validaciones por paso y el
 * submit) para que campaign-editor-page.tsx quede solo como orquestación.
 */
export const useCampaignEditor = (id: string | undefined, portfolioId: string) => {
  const navigate = useNavigate();
  const { apiClient } = useApiClient();
  const { orgId, buildOrgPath } = useOrgModule();
  const { success } = useToast();
  const isEditing = !!id;

  const { portfolios } = usePortfolios(orgId);
  const portfolio = portfolios.find((p) => p.id === portfolioId);
  const portfolioName = portfolio?.name ?? "Portafolio";
  const { countries } = useCountries();
  const portfolioTimezone = countries.find((c) => c.code === portfolio?.country)?.timezone ?? "UTC";

  const { segments } = useSegmentOptions(portfolioId);
  const { templates } = useTemplateOptions(portfolioId);
  const { variables } = useTemplateVariables(orgId);
  const { channels } = useChannels();
  const { periodicities } = useCampaignPeriodicities(orgId);
  const { weekdays } = useCampaignWeekdays(orgId);
  const recurringPeriodicities = periodicities.filter(
    (p) => p.value === "DIARIO" || p.value === "SEMANAL" || p.value === "MENSUAL",
  );

  const [form, setForm] = useState<CampaignEditorFormState>(EMPTY);
  const [loadingCampaign, setLoadingCampaign] = useState(isEditing);
  const [saving, setSaving] = useState(false);

  // La campaña usa la zona horaria del país del portfolio donde se crea;
  // no se le pide al usuario.
  useEffect(() => {
    if (!isEditing) setForm((prev) => ({ ...prev, timezone: portfolioTimezone }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isEditing, portfolioTimezone]);

  const selectedChannel = channels.find((c) => c.id === form.channelId);
  const channelName = selectedChannel?.name;
  const isCall = channelName === "CALL";

  const { flows: ivrFlows, loading: loadingFlows } = useIvrFlows(portfolioId);
  const designerHref = (flowId?: string) =>
    buildOrgPath("/my-companies/campaigns/ivr", {
      portfolio: portfolioId,
      ...(flowId ? { flowId } : {}),
    });

  // Plantillas: solo EMAIL/SMS existen hoy; WHATSAPP/CALL no tiene plantillas
  // compatibles todavía (se envía el mensaje libre / flujo IVR).
  const compatibleTemplates = templates.filter((t) => t.channel === channelName);
  const selectedTemplate = templates.find((t) => t.id === form.templateId) ?? null;
  const showsSubject = channelName === "EMAIL";

  useEffect(() => {
    if (form.templateId && !compatibleTemplates.some((t) => t.id === form.templateId)) {
      setForm((prev) => ({ ...prev, templateId: "" }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.channelId, templates]);

  useEffect(() => {
    if (!isEditing && !form.channelId && channels.length > 0) {
      setForm((prev) => ({ ...prev, channelId: channels[0].id }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channels]);

  // El mensaje siempre refleja el contenido de la plantilla elegida: no se
  // pide manualmente cuando hay una plantilla seleccionada.
  useEffect(() => {
    if (!form.templateId) return;
    const tpl = templates.find((t) => t.id === form.templateId);
    if (!tpl) return;
    setForm((prev) => ({
      ...prev,
      message: tpl.body,
      subject: prev.subject || (tpl.subject ?? ""),
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.templateId, templates]);

  const backPath = buildOrgPath("/my-companies/campaigns", { portfolio: portfolioId });

  useEffect(() => {
    if (!isEditing || !orgId) return;
    apiClient(`/campaigns/${id}?portfolioId=${portfolioId}`, { method: "GET" })
      .then((c: Campaign) => {
        const frequency: CampaignFrequency = c.isImmediate
          ? "INMEDIATO"
          : c.periodicity === "UNA_VEZ"
            ? "UNA_VEZ"
            : "PERIODICO";
        const recurringPeriodicity: RecurringPeriodicity =
          c.periodicity === "DIARIO" || c.periodicity === "SEMANAL" || c.periodicity === "MENSUAL"
            ? c.periodicity
            : "SEMANAL";
        setForm({
          name: c.name,
          description: c.description ?? "",
          channelId: c.channelId,
          segmentId: c.segmentId ?? "",
          templateId: c.templateId ?? "",
          ivrFlowId: c.ivrFlowId ?? "",
          message: c.message,
          subject: c.subject ?? "",
          fallback: c.fallback,
          timezone: c.timezone,
          frequency,
          recurringPeriodicity,
          scheduledAt: c.scheduledAt ? c.scheduledAt.slice(0, 16) : "",
          timeToSend: c.timeToSend ? c.timeToSend.slice(0, 5) : "",
          daysOfWeek: c.daysOfWeek ?? [],
          dayOfMonth: c.dayOfMonth ?? null,
        });
      })
      .catch(() => navigate(backPath))
      .finally(() => setLoadingCampaign(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const set = <K extends keyof CampaignEditorFormState>(key: K) =>
    (value: CampaignEditorFormState[K]) =>
      setForm((prev) => ({ ...prev, [key]: value }));

  const detailsValid = form.name.trim() !== "";
  const channelValid = !!form.channelId;
  const messageValid = isCall ? !!form.ivrFlowId : !!selectedTemplate;
  const scheduleValid =
    form.frequency === "INMEDIATO"
      ? true
      : form.frequency === "UNA_VEZ"
        ? !!form.scheduledAt
        : !!form.recurringPeriodicity &&
          !!form.timeToSend &&
          (form.recurringPeriodicity !== "SEMANAL" || form.daysOfWeek.length > 0) &&
          (form.recurringPeriodicity !== "MENSUAL" || !!form.dayOfMonth);

  const canSubmit = detailsValid && channelValid && messageValid && scheduleValid;

  const canAdvance = (step: number) => {
    if (step === 0) return detailsValid;
    if (step === 1) return channelValid;
    if (step === 2) return messageValid;
    return true;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);

    const isImmediate = form.frequency === "INMEDIATO";
    const periodicity =
      form.frequency === "INMEDIATO"
        ? "INMEDIATO"
        : form.frequency === "UNA_VEZ"
          ? "UNA_VEZ"
          : form.recurringPeriodicity;

    const payload = {
      name: form.name.trim(),
      description: form.description.trim() || null,
      channelId: form.channelId,
      segmentId: form.segmentId || null,
      templateId: isCall ? null : form.templateId || null,
      ivrFlowId: isCall ? form.ivrFlowId || null : null,
      message: isCall ? "" : form.message,
      subject: showsSubject ? form.subject.trim() || null : null,
      fallback: form.fallback,
      timezone: form.timezone.trim() || "UTC",
      isImmediate,
      periodicity,
      scheduledAt:
        form.frequency === "UNA_VEZ" && form.scheduledAt
          ? new Date(form.scheduledAt).toISOString()
          : null,
      timeToSend: form.frequency === "PERIODICO" && form.timeToSend ? `${form.timeToSend}:00` : null,
      daysOfWeek:
        form.frequency === "PERIODICO" && form.recurringPeriodicity === "SEMANAL" && form.daysOfWeek.length > 0
          ? form.daysOfWeek
          : null,
      dayOfMonth:
        form.frequency === "PERIODICO" && form.recurringPeriodicity === "MENSUAL" ? form.dayOfMonth : null,
    };

    try {
      if (isEditing) {
        await apiClient(`/campaigns/${id}?portfolioId=${portfolioId}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
      } else {
        await apiClient(`/campaigns/?portfolioId=${portfolioId}`, {
          method: "POST",
          body: JSON.stringify(payload),
        });
      }
      success(isEditing ? "Campaña actualizada" : "Campaña creada");
      navigate(backPath);
    } finally {
      setSaving(false);
    }
  };

  return {
    isEditing,
    orgId,
    portfolioName,
    form,
    set,
    loadingCampaign,
    saving,
    segments,
    channels,
    compatibleTemplates,
    selectedTemplate,
    showsSubject,
    isCall,
    ivrFlows,
    loadingFlows,
    designerHref,
    variables,
    recurringPeriodicities,
    weekdays,
    canSubmit,
    canAdvance,
    handleSubmit,
    backPath,
  };
};
