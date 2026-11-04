import { FileText, Image, Paperclip, X, type LucideIcon } from "lucide-react";
import { Select } from "@/ui/components/inputs/select";
import { Textarea } from "@/ui/components/inputs/textarea";
import { TICKET_CATEGORY_ICON_MAP } from "@/support/constants/ticket-category-icons";
import { IMAGE_ATTACHMENT_EXTENSIONS } from "@/support/constants/ticket-attachment-types";
import type { StepDetailsProps } from "@/support/types/step-details-props";

const FileIcon: React.FC<{ name: string }> = ({ name }) => {
  const ext = name.slice(name.lastIndexOf(".")).toLowerCase();
  return IMAGE_ATTACHMENT_EXTENSIONS.has(ext) ? (
    <Image size={14} className="text-brand-500" />
  ) : (
    <FileText size={14} className="text-gray-500 dark:text-gray-400" />
  );
};

export const StepDetails: React.FC<StepDetailsProps> = ({
  selectedCategory,
  isGlobal,
  orgs,
  loadingOrgs,
  organizationId,
  onOrganizationIdChange,
  notes,
  onNotesChange,
  attachments,
  onAddFiles,
  onRemoveFile,
  submitting,
  onSubmit,
  onBack,
}) => {
  const SelectedCategoryIcon: LucideIcon | null = selectedCategory
    ? (TICKET_CATEGORY_ICON_MAP[selectedCategory.icon] ?? null)
    : null;

  return (
    <form onSubmit={onSubmit} className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-800 dark:text-white/90">Detalles del ticket</h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Completa la información de tu solicitud.
        </p>
      </div>

      {selectedCategory && SelectedCategoryIcon && (
        <div className="flex items-center gap-3 rounded-xl border border-brand-200 bg-brand-50 px-4 py-3 dark:border-brand-500/30 dark:bg-brand-500/10">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand-100 text-brand-600 dark:bg-brand-500/20 dark:text-brand-400">
            <SelectedCategoryIcon size={15} />
          </div>
          <div>
            <p className="text-xs text-brand-500 dark:text-brand-400">Categoría seleccionada</p>
            <p className="text-sm font-semibold text-brand-700 dark:text-brand-300">{selectedCategory.label}</p>
          </div>
        </div>
      )}

      {!isGlobal ? (
        <div>
          <label className="mb-1.5 block text-sm font-medium text-gray-700 dark:text-gray-300">
            Entidad <span className="text-error-500">*</span>
          </label>
          {loadingOrgs ? (
            <div className="h-10 animate-pulse rounded-lg bg-gray-100 dark:bg-white/5" />
          ) : (
            <Select
              value={organizationId}
              onChange={onOrganizationIdChange}
              placeholder="Seleccionar entidad..."
              options={orgs.map((org) => ({ value: org.id, label: org.name }))}
            />
          )}
        </div>
      ) : orgs.length > 0 ? (
        <div>
          <label className="mb-1.5 block text-sm font-medium text-gray-700 dark:text-gray-300">
            Entidad <span className="font-normal text-gray-400">(opcional)</span>
          </label>
          {loadingOrgs ? (
            <div className="h-10 animate-pulse rounded-lg bg-gray-100 dark:bg-white/5" />
          ) : (
            <Select
              value={organizationId}
              onChange={onOrganizationIdChange}
              placeholder="Sin entidad específica"
              options={orgs.map((org) => ({ value: org.id, label: org.name }))}
            />
          )}
        </div>
      ) : null}

      <div>
        <label className="mb-1.5 block text-sm font-medium text-gray-700 dark:text-gray-300">
          Descripción <span className="text-error-500">*</span>
        </label>
        <Textarea
          value={notes}
          onChange={(e) => onNotesChange(e.target.value)}
          placeholder="Describe el problema con el mayor detalle posible: pasos para reproducirlo, mensajes de error, capturas de pantalla relevantes..."
          rows={5}
          className="resize-none"
        />
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-gray-700 dark:text-gray-300">
          Adjuntos{" "}
          <span className="font-normal text-gray-400">(opcional · .pdf, .jpg, .png)</span>
        </label>
        <label
          className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-gray-300 px-4 py-5 transition-colors hover:border-brand-400 hover:bg-brand-50 dark:border-gray-700 dark:hover:border-brand-500 dark:hover:bg-brand-500/10"
        >
          <Paperclip size={22} className="text-gray-400" />
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Arrastra aquí o <span className="font-medium text-brand-500">selecciona archivos</span>
          </p>
          <input
            type="file"
            multiple
            accept=".pdf,.jpg,.jpeg,.png"
            className="hidden"
            onChange={(e) => onAddFiles(e.target.files)}
          />
        </label>
        {attachments.length > 0 && (
          <ul className="mt-2 flex flex-col gap-1.5">
            {attachments.map((f) => (
              <li
                key={f.name}
                className="flex items-center gap-2 rounded-lg border border-gray-100 bg-gray-50 px-3 py-2 dark:border-gray-800 dark:bg-white/3"
              >
                <FileIcon name={f.name} />
                <span className="min-w-0 flex-1 truncate text-sm text-gray-700 dark:text-gray-300">
                  {f.name}
                </span>
                <button
                  type="button"
                  onClick={() => onRemoveFile(f.name)}
                  className="text-gray-400 hover:text-error-500"
                >
                  <X size={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex flex-col-reverse gap-3 pt-2 sm:flex-row sm:justify-end">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-white px-5 py-3 text-sm font-medium text-gray-700 ring-1 ring-inset ring-gray-300 transition hover:bg-gray-50 dark:bg-gray-800 dark:text-gray-400 dark:ring-gray-700 dark:hover:bg-white/3"
        >
          Atrás
        </button>
        <button
          type="submit"
          disabled={(!isGlobal && !organizationId) || !notes.trim() || submitting}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-brand-500 px-6 py-3 text-sm font-medium text-white shadow-theme-xs transition hover:bg-brand-600 disabled:opacity-50"
        >
          {submitting ? "Creando..." : "Crear ticket"}
        </button>
      </div>
    </form>
  );
};
