import { useEffect, useState } from "react";
import { useApiClient } from "@/hooks/use-api-client";
import { useToast } from "@/context/toast-context";
import { CHANNEL_CHAR_LIMITS, UNAVAILABLE_CHANNELS } from "@/templates/constants/template-wizard-options";
import { useWhatsAppTemplateForm } from "@/templates/hooks/use-whatsapp-template-form";
import type { Template } from "@/types/templates/template-types";
import type { TemplateEditorFormState } from "@/templates/types/template-editor-form-state";
import type { TemplateVariableOption } from "@/templates/types/template-variable-option";

const EMPTY: TemplateEditorFormState = {
  name: "",
  channel: "EMAIL",
  status: "BORRADOR",
  body: "",
  design: null,
  subject: "",
  senderName: "",
  senderEmail: "",
  replyTo: "",
};

export const useTemplateEditorForm = (
  portfolioId: string,
  id: string | undefined,
  onSaved: () => void,
  onLoadError: () => void,
  variables: TemplateVariableOption[],
) => {
  const { apiClient } = useApiClient();
  const { success, error } = useToast();
  const isEditing = !!id;

  const [form, setForm] = useState<TemplateEditorFormState>(EMPTY);
  const [loadingTemplate, setLoadingTemplate] = useState(isEditing);
  const [saving, setSaving] = useState(false);
  const whatsapp = useWhatsAppTemplateForm(portfolioId, variables);

  useEffect(() => {
    if (!isEditing || !portfolioId) return;
    apiClient(`/templates/${id}?portfolioId=${portfolioId}`, { method: "GET" })
      .then((t: Template) => {
        // El contenido de una plantilla de WhatsApp vive en Meta: no se edita desde acá.
        if (t.channel === "WHATSAPP") {
          error("Plantilla de WhatsApp", "No se puede editar. Elimínala y crea una nueva.");
          onLoadError();
          return;
        }
        setForm({
          name: t.name,
          channel: t.channel,
          status: t.status,
          body: t.body,
          design: t.design ?? null,
          subject: t.subject ?? "",
          senderName: t.senderName ?? "",
          senderEmail: t.senderEmail ?? "",
          replyTo: t.replyTo ?? "",
        });
      })
      .catch(onLoadError)
      .finally(() => setLoadingTemplate(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const set = <K extends keyof TemplateEditorFormState>(key: K) =>
    (value: TemplateEditorFormState[K]) =>
      setForm((prev) => ({ ...prev, [key]: value }));

  const isEmail = form.channel === "EMAIL";
  const isWhatsApp = form.channel === "WHATSAPP";
  const isUnavailable = UNAVAILABLE_CHANNELS.includes(form.channel);
  const charLimit = CHANNEL_CHAR_LIMITS[form.channel];
  const withinCharLimit = charLimit === undefined || form.body.length <= charLimit;

  const isDesignValid = isWhatsApp
    ? whatsapp.isDesignValid
    : !isUnavailable && form.body.trim() !== "" && withinCharLimit;

  const canAdvance = (step: number) => {
    if (isWhatsApp) return whatsapp.canAdvance(step, form.name);
    if (step === 0) return true;
    if (step === 1) {
      if (!form.name.trim()) return false;
      if (isEmail) return !!form.subject.trim() && !!form.senderEmail.trim();
      return true;
    }
    if (step === 2) return isDesignValid;
    return false;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isWhatsApp) {
      await whatsapp.submit(form.name, onSaved);
      return;
    }
    setSaving(true);
    const payload = {
      name: form.name.trim(),
      channel: form.channel,
      status: form.status,
      body: form.body,
      design: isEmail ? form.design : null,
      subject: isEmail ? form.subject.trim() || null : null,
      senderName: form.senderName.trim() || null,
      senderEmail: isEmail ? form.senderEmail.trim() || null : null,
      replyTo: isEmail ? form.replyTo.trim() || null : null,
    };
    try {
      if (isEditing) {
        await apiClient(`/templates/${id}?portfolioId=${portfolioId}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
      } else {
        await apiClient(`/templates/?portfolioId=${portfolioId}`, {
          method: "POST",
          body: JSON.stringify(payload),
        });
      }
      success(isEditing ? "Plantilla actualizada" : "Plantilla creada");
      onSaved();
    } finally {
      setSaving(false);
    }
  };

  return {
    form,
    set,
    isEditing,
    loadingTemplate,
    saving: saving || whatsapp.saving,
    isEmail,
    isWhatsApp,
    whatsapp,
    isUnavailable,
    charLimit,
    isDesignValid,
    canAdvance,
    handleSubmit,
  };
};
