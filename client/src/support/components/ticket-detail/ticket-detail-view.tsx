import { useState } from "react";
import { Card, CardTitle } from "@/ui/components/card";
import { Badge } from "@/ui/components/badge";
import { ArrowUpCircle, CheckCircle, FileText, Paperclip, X } from "lucide-react";
import { resolveProfilePhotoUrl } from "@/profile/utils/profile-photo-url";
import { useTicketCreator } from "@/support/hooks/use-ticket-creator";
import { useTicketAssignee } from "@/support/hooks/use-ticket-assignee";
import { useEscalateTicket } from "@/support/hooks/use-escalate-ticket";
import { useResolveTicket } from "@/support/hooks/use-resolve-ticket";
import { useUploadClosureAttachments } from "@/support/hooks/use-upload-closure-attachments";
import { TicketOrgDocsViewer } from "./ticket-org-docs-viewer";
import { TicketAttachments } from "./ticket-attachments";
import { TicketClosureAttachments } from "./ticket-closure-attachments";
import { TicketConversation } from "./ticket-conversation";
import { TicketAuditLog } from "./ticket-audit-log";
import { Button } from "@/ui/components/button/button";
import {
  formatTicketDetailDate,
  getPriorityBadgeColor,
  getStatusBadgeColor,
  getTicketDisplayId,
  TICKET_CASE_TYPE_LABELS,
  TICKET_PRIORITY_LABELS,
  TICKET_STATUS_LABELS,
  TICKET_TYPE_LABELS,
} from "@/support/utils/ticket-kanban-utils";
import { useTicketPermissions } from "@/support/hooks/use-ticket-permissions";
import type { TicketDetailViewProps } from "@/types/props/ticket-detail-view-props";

const UserAvatar: React.FC<{ name: string; photoUrl?: string | null; size?: "sm" | "md" }> = ({
  name,
  photoUrl,
  size = "md",
}) => {
  const url = resolveProfilePhotoUrl(photoUrl);
  const initials = name
    .split(" ")
    .slice(0, 2)
    .map((w) => w[0] ?? "")
    .join("")
    .toUpperCase();
  const dim = size === "sm" ? "size-7 text-xs" : "size-9 text-sm";

  return (
    <div className={`shrink-0 overflow-hidden rounded-full border border-gray-200 dark:border-gray-700 ${dim}`}>
      {url ? (
        <img src={url} alt={name} className="size-full object-cover" />
      ) : (
        <div className={`flex size-full items-center justify-center bg-brand-500 font-semibold text-white ${dim}`}>
          {initials}
        </div>
      )}
    </div>
  );
};

const DetailRow: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div className="rounded-lg border border-gray-100 bg-gray-50 px-4 py-3 dark:border-gray-800 dark:bg-white/3">
    <p className="text-xs text-gray-400 dark:text-gray-500">{label}</p>
    <div className="mt-1 text-sm font-medium text-gray-800 dark:text-white/90">{children}</div>
  </div>
);

export const TicketDetailView: React.FC<TicketDetailViewProps> = ({ ticket, onTicketResolved, onTicketEscalated }) => {
  const { canResolve, canEscalate } = useTicketPermissions(ticket.status);
  const { creator } = useTicketCreator(ticket.createdBy);
  const { assignee } = useTicketAssignee(ticket.assignedTo ?? undefined);
  const { escalateTicket, loading: escalating } = useEscalateTicket();
  const { resolveTicket, loading: resolving } = useResolveTicket();
  const { uploadClosureAttachments, loading: uploading } = useUploadClosureAttachments();
  const [showResolveForm, setShowResolveForm] = useState(false);
  const [resolveNotes, setResolveNotes] = useState("");
  const [closureFiles, setClosureFiles] = useState<File[]>([]);
  const [closureKey, setClosureKey] = useState(0);
  const isOrgVerification = ticket.topic === "VALIDACION_DOCUMENTO";
  const displayId = getTicketDisplayId(ticket.ticketNumber, ticket.caseType);
  const isResolved = ticket.status === "RESUELTO";

  const handleEscalate = async () => {
    const updated = await escalateTicket(ticket.ticketNumber);
    if (updated) onTicketEscalated?.(updated);
  };

  const handleResolve = async () => {
    if (!resolveNotes.trim()) return;
    if (closureFiles.length) {
      await uploadClosureAttachments(ticket.ticketNumber, closureFiles);
    }
    const updated = await resolveTicket(ticket.ticketNumber, { approved: true, notes: resolveNotes });
    if (updated) {
      onTicketResolved?.(updated);
      setShowResolveForm(false);
      setResolveNotes("");
      setClosureFiles([]);
      setClosureKey((k) => k + 1);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files ?? []);
    setClosureFiles((prev) => {
      const existing = new Set(prev.map((f) => f.name));
      return [...prev, ...selected.filter((f) => !existing.has(f.name))];
    });
    e.target.value = "";
  };

  const removeFile = (name: string) => setClosureFiles((prev) => prev.filter((f) => f.name !== name));

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
      <Card>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="mb-2 flex items-center gap-2">
              <span className="inline-flex items-center rounded-md bg-brand-50 px-2.5 py-1 text-xs font-bold tracking-widest text-brand-600 dark:bg-brand-500/10 dark:text-brand-400">
                {displayId}
              </span>
              <span className="text-xs font-medium text-gray-400 dark:text-gray-500">
                {TICKET_TYPE_LABELS[ticket.caseType]}
              </span>
            </div>
            <h2 className="text-title-sm font-semibold text-gray-800 dark:text-white/90">
              {ticket.title ?? TICKET_CASE_TYPE_LABELS[ticket.caseType]}
            </h2>
          </div>
          <div className="w-fit shrink-0">
            <Badge color={getStatusBadgeColor(ticket.status)}>{TICKET_STATUS_LABELS[ticket.status]}</Badge>
          </div>
        </div>

        <div className="mt-6 rounded-xl border border-gray-100 bg-gray-50 p-4 dark:border-gray-800 dark:bg-white/3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
            {isResolved ? "Nota de cierre" : "Notas"}
          </p>
          <p className="whitespace-pre-line text-sm text-gray-700 dark:text-gray-300">
            {ticket.notes ?? "Este ticket todavía no tiene notas registradas."}
          </p>
        </div>

        <TicketConversation ticketNumber={ticket.ticketNumber} status={ticket.status} />

        {isResolved && !isOrgVerification && (
          <TicketClosureAttachments ticketNumber={ticket.ticketNumber} refreshTrigger={closureKey} />
        )}

        {isOrgVerification && (
          <TicketOrgDocsViewer
            ticket={ticket}
            onResolved={onTicketResolved ?? (() => {})}
          />
        )}

        {/* Resolve action for INCIDENT tickets */}
        {!isOrgVerification && canResolve && !isResolved && (
          <div className="mt-6">
            {!showResolveForm ? (
              <button
                type="button"
                onClick={() => setShowResolveForm(true)}
                className="inline-flex items-center gap-2 rounded-lg bg-success-50 px-4 py-2 text-sm font-medium text-success-700 hover:bg-success-100 dark:bg-success-500/10 dark:text-success-400 dark:hover:bg-success-500/20"
              >
                <CheckCircle size={15} />
                Resolver ticket
              </button>
            ) : (
              <div className="rounded-xl border border-gray-100 bg-gray-50 p-4 dark:border-gray-800 dark:bg-white/3">
                <p className="mb-2 text-sm font-medium text-gray-700 dark:text-gray-300">Cerrando ticket</p>
                <textarea
                  value={resolveNotes}
                  onChange={(e) => setResolveNotes(e.target.value)}
                  placeholder="Nota de cierre obligatoria..."
                  rows={3}
                  className="w-full resize-none rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 placeholder-gray-400 focus:border-brand-300 focus:outline-none dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300 dark:placeholder-gray-600 dark:focus:border-brand-500"
                />
                {!resolveNotes.trim() && (
                  <p className="mt-1 text-xs text-error-500">La nota de cierre es obligatoria.</p>
                )}

                <div className="mt-3">
                  <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-dashed border-gray-200 px-3 py-2 text-xs font-medium text-gray-500 hover:border-brand-300 hover:text-brand-600 dark:border-gray-700 dark:text-gray-400 dark:hover:border-brand-500 dark:hover:text-brand-400">
                    <Paperclip size={13} />
                    Adjuntar archivos de cierre
                    <input
                      type="file"
                      className="sr-only"
                      multiple
                      accept=".jpg,.jpeg,.png,.pdf"
                      onChange={handleFileChange}
                    />
                  </label>
                  {closureFiles.length > 0 && (
                    <ul className="mt-2 flex flex-col gap-1">
                      {closureFiles.map((f) => (
                        <li key={f.name} className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
                          <FileText size={12} className="shrink-0" />
                          <span className="min-w-0 flex-1 truncate">{f.name}</span>
                          <button type="button" onClick={() => removeFile(f.name)} className="shrink-0 text-gray-400 hover:text-error-500">
                            <X size={12} />
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    onClick={handleResolve}
                    disabled={resolving || uploading || !resolveNotes.trim()}
                    className="inline-flex items-center gap-2 rounded-lg bg-success-500 px-4 py-2 text-sm font-medium text-white hover:bg-success-600 disabled:opacity-60"
                  >
                    {resolving || uploading ? "Procesando..." : "Confirmar"}
                  </button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => { setShowResolveForm(false); setResolveNotes(""); setClosureFiles([]); }}
                  >
                    Cancelar
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}

        {!isOrgVerification && isResolved && (
          <p className="mt-6 flex items-center gap-1.5 text-sm text-success-600 dark:text-success-400">
            <CheckCircle size={14} />
            Ticket resuelto
          </p>
        )}

        <TicketAttachments ticketNumber={ticket.ticketNumber} />
      </Card>

      <Card>
        <CardTitle>Detalle del ticket</CardTitle>
        <div className="mt-5 flex flex-col gap-3">
          <DetailRow label="Creado por">
            {creator ? (
              <div className="flex items-center gap-2.5">
                <UserAvatar name={creator.fullName} photoUrl={creator.profilePhotoUrl} size="sm" />
                <span>{creator.fullName}</span>
              </div>
            ) : (
              <span className="text-gray-500">Usuario #{ticket.createdBy}</span>
            )}
          </DetailRow>

          <DetailRow label="Asignado a">
            {ticket.assignedTo ? (
              assignee ? (
                <div className="flex items-center gap-2.5">
                  <UserAvatar name={assignee.fullName} photoUrl={assignee.profilePhotoUrl} size="sm" />
                  <span>{assignee.fullName}</span>
                </div>
              ) : (
                <span className="text-gray-500">Usuario #{ticket.assignedTo}</span>
              )
            ) : (
              <span className="text-gray-400 dark:text-gray-500">Sin asignar</span>
            )}
          </DetailRow>

          <DetailRow label="Entidad">
            <span>{ticket.organizationName || ticket.organizationId}</span>
          </DetailRow>

          <DetailRow label="Creado">
            {formatTicketDetailDate(ticket.createdAt)}
          </DetailRow>

          <DetailRow label="Resuelto">
            <span className={ticket.resolvedAt ? "" : "text-gray-400 dark:text-gray-500"}>
              {formatTicketDetailDate(ticket.resolvedAt)}
            </span>
          </DetailRow>

          <div className="rounded-lg border border-gray-100 bg-gray-50 px-4 py-3 dark:border-gray-800 dark:bg-white/3">
            <p className="mb-1.5 text-xs text-gray-400 dark:text-gray-500">Prioridad</p>
            <Badge color={getPriorityBadgeColor(ticket.priority)}>{TICKET_PRIORITY_LABELS[ticket.priority]}</Badge>
          </div>

          <div className="rounded-lg border border-gray-100 bg-gray-50 px-4 py-3 dark:border-gray-800 dark:bg-white/3">
            <p className="mb-1.5 text-xs text-gray-400 dark:text-gray-500">Tipo</p>
            <span
              className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                isOrgVerification
                  ? "bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-400"
                  : "bg-error-50 text-error-700 dark:bg-error-500/10 dark:text-error-400"
              }`}
            >
              {displayId.split("-")[0]} · {TICKET_TYPE_LABELS[ticket.caseType]}
            </span>
          </div>

          <TicketAuditLog ticketNumber={ticket.ticketNumber} />

          {canEscalate && !isResolved && (
            <button
              type="button"
              onClick={handleEscalate}
              disabled={escalating}
              className="mt-1 inline-flex w-full items-center justify-center gap-2 rounded-lg border border-warning-200 bg-warning-50 px-4 py-2.5 text-sm font-medium text-warning-700 hover:bg-warning-100 disabled:opacity-60 dark:border-warning-500/30 dark:bg-warning-500/10 dark:text-warning-400 dark:hover:bg-warning-500/20"
            >
              <ArrowUpCircle size={15} />
              {escalating ? "Escalando..." : "Escalar a CS Global"}
            </button>
          )}
        </div>
      </Card>
    </div>
  );
};
