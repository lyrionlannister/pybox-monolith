import { useMemo, useState } from "react";
import type { DatesSetArg, EventClickArg } from "@fullcalendar/core";
import type { Campaign, CampaignOccurrence, Periodicity } from "@/types/campaigns/campaign-types";
import type { CampaignEditorFormState } from "@/campaigns/types/campaign-editor-form-state";
import { useModal } from "@/hooks/use-modal";
import { useApiClient } from "@/hooks/use-api-client";
import { useCampaignTimeline } from "@/campaigns/hooks/use-campaign-timeline";
import { useCampaignPeriodicities } from "@/campaigns/hooks/use-campaign-periodicities";
import { useCampaignWeekdays } from "@/campaigns/hooks/use-campaign-weekdays";
import { CAMPAIGN_EDITABLE_STATUSES } from "@/campaigns/constants/campaign-calendar-meta";
import { buildCalendarEvents, buildCampaignEditorForm } from "@/campaigns/utils/campaign-utils";

/**
 * Encapsula fetch (timeline, detalle al hacer click, guardado de reprogramación)
 * y estado del calendario de campañas para que campaigns-calendar.tsx quede
 * solo como componente de presentación.
 */
export const useCampaignCalendar = (organizationId: string, isAdmin: boolean) => {
  const { apiClient } = useApiClient();
  const [range, setRange] = useState<{ from: string; to: string }>({ from: "", to: "" });
  const [selected, setSelected] = useState<CampaignOccurrence | null>(null);
  const [form, setForm] = useState<CampaignEditorFormState | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [saving, setSaving] = useState(false);
  const { isOpen, openModal, closeModal } = useModal();

  const { occurrences, loading, error, refetch } = useCampaignTimeline(
    organizationId,
    range.from,
    range.to,
  );
  const { periodicities } = useCampaignPeriodicities(organizationId);
  const { weekdays } = useCampaignWeekdays(organizationId);
  const recurringPeriodicities = periodicities.filter(
    (p) => p.value === "DIARIO" || p.value === "SEMANAL" || p.value === "MENSUAL",
  );

  const events = useMemo(() => buildCalendarEvents(occurrences), [occurrences]);

  const canEdit = !!selected && isAdmin && CAMPAIGN_EDITABLE_STATUSES.includes(selected.status);

  const handleDatesSet = (arg: DatesSetArg) => {
    const from = arg.start.toISOString();
    const to = arg.end.toISOString();
    setRange((prev) => (prev.from === from && prev.to === to ? prev : { from, to }));
  };

  const handleClick = (info: EventClickArg) => {
    const occurrence = (info.event.extendedProps as { occurrence: CampaignOccurrence }).occurrence;
    setSelected(occurrence);
    setForm(null);
    openModal();
    if (isAdmin && CAMPAIGN_EDITABLE_STATUSES.includes(occurrence.status)) {
      setLoadingDetail(true);
      apiClient(`/campaigns/${occurrence.campaignId}?portfolioId=${occurrence.portfolioId}`, { method: "GET" })
        .then((c: Campaign) => setForm(buildCampaignEditorForm(c)))
        .catch(() => setForm(null))
        .finally(() => setLoadingDetail(false));
    }
  };

  const setField =
    <K extends keyof CampaignEditorFormState>(key: K) =>
    (value: CampaignEditorFormState[K]) =>
      setForm((prev) => (prev ? { ...prev, [key]: value } : prev));

  const handleSave = async () => {
    if (!selected || !form) return;
    const isImmediate = form.frequency === "INMEDIATO";
    const periodicity: Periodicity =
      form.frequency === "INMEDIATO"
        ? "INMEDIATO"
        : form.frequency === "UNA_VEZ"
          ? "UNA_VEZ"
          : form.recurringPeriodicity;

    const payload = {
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

    setSaving(true);
    try {
      await apiClient(`/campaigns/${selected.campaignId}?portfolioId=${selected.portfolioId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      handleClose();
      refetch();
    } catch {
      /* el apiClient ya muestra el toast de error */
    } finally {
      setSaving(false);
    }
  };

  const handleClose = () => {
    closeModal();
    setSelected(null);
    setForm(null);
  };

  return {
    events,
    loading,
    error,
    refetch,
    isOpen,
    selected,
    form,
    loadingDetail,
    saving,
    canEdit,
    recurringPeriodicities,
    weekdays,
    handleDatesSet,
    handleClick,
    setField,
    handleSave,
    handleClose,
  };
};
