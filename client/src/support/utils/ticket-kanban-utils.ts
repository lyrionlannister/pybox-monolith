import { formatDateTimeLong } from "@/utils/format-date";
import type { BadgeColor } from "@/types/props/badge-props";
import type {
  SupportCaseType,
  SupportTicket,
  SupportTicketPriority,
  SupportTicketStatus,
} from "@/types/support/support-types";
import type {
  TicketKanban,
  TicketKanbanCategory,
  TicketKanbanColumnDefinition,
  TicketKanbanGroup,
  TicketKanbanGroupKey,
} from "@/types/support/ticket-kanban-types";

export const TICKET_KANBAN_COLUMNS: TicketKanbanColumnDefinition[] = [
  { title: "Nuevos", status: "NUEVO" },
  { title: "Abiertos", status: "ABIERTO" },
  { title: "En proceso", status: "EN_PROGRESO" },
  { title: "Pend. cliente", status: "PENDIENTE_CLIENTE" },
  { title: "Pend. tercero", status: "PENDIENTE_TERCERO" },
  { title: "Resueltos", status: "RESUELTO" },
  { title: "Cerrados", status: "CERRADO" },
];

export const TICKET_STATUS_LABELS: Record<SupportTicketStatus, string> = {
  NUEVO: "Nuevo",
  ABIERTO: "Abierto",
  EN_PROGRESO: "En proceso",
  PENDIENTE_CLIENTE: "Pend. cliente",
  PENDIENTE_TERCERO: "Pend. tercero",
  RESUELTO: "Resuelto",
  CERRADO: "Cerrado",
};

export const TICKET_PRIORITY_LABELS: Record<SupportTicketPriority, string> = {
  BAJA: "Baja",
  MEDIA: "Media",
  ALTA: "Alta",
  URGENTE: "Urgente",
};

export const TICKET_CASE_TYPE_LABELS: Record<SupportCaseType, string> = {
  REQUERIMIENTO: "Requerimiento",
  INCIDENTE: "Incidente",
};

export const TICKET_TYPE_LABELS = TICKET_CASE_TYPE_LABELS;

const TICKET_PREFIX: Record<SupportCaseType, string> = {
  REQUERIMIENTO: "RT",
  INCIDENTE: "IT",
};

export const getTicketDisplayId = (ticketNumber: number, caseType: SupportCaseType): string =>
  `${TICKET_PREFIX[caseType]}-${String(ticketNumber).padStart(6, "0")}`;

export const isTicketFromToday = (ticket: SupportTicket): boolean => {
  const date = new Date(ticket.createdAt);
  const today = new Date();

  return (
    date.getFullYear() === today.getFullYear() &&
    date.getMonth() === today.getMonth() &&
    date.getDate() === today.getDate()
  );
};

export const getTicketKanbanGroups = (
  tickets: TicketKanban[],
): TicketKanbanGroup[] => [
  { name: "Todos", key: "all", count: tickets.length },
  { name: "Nuevos", key: "NUEVO", count: tickets.filter((t) => t.status === "NUEVO").length },
  { name: "Abiertos", key: "ABIERTO", count: tickets.filter((t) => t.status === "ABIERTO").length },
  { name: "En proceso", key: "EN_PROGRESO", count: tickets.filter((t) => t.status === "EN_PROGRESO").length },
  { name: "Pend. cliente", key: "PENDIENTE_CLIENTE", count: tickets.filter((t) => t.status === "PENDIENTE_CLIENTE").length },
  { name: "Pend. tercero", key: "PENDIENTE_TERCERO", count: tickets.filter((t) => t.status === "PENDIENTE_TERCERO").length },
  { name: "Resueltos", key: "RESUELTO", count: tickets.filter((t) => t.status === "RESUELTO").length },
  { name: "Cerrados", key: "CERRADO", count: tickets.filter((t) => t.status === "CERRADO").length },
];

export const getFilteredKanbanTickets = (
  tickets: TicketKanban[],
  selectedGroup: TicketKanbanGroupKey,
): TicketKanban[] => {
  if (selectedGroup === "all") return tickets;

  return tickets.filter((ticket) => ticket.status === selectedGroup);
};

export const getVisibleKanbanColumns = (
  selectedGroup: TicketKanbanGroupKey,
): TicketKanbanColumnDefinition[] => {
  if (selectedGroup === "all") return TICKET_KANBAN_COLUMNS;

  return TICKET_KANBAN_COLUMNS.filter(
    (column) => column.status === selectedGroup,
  );
};

export const mapTicketToKanban = (ticket: SupportTicket): TicketKanban => {
  const category = getTicketCategory(ticket.caseType);
  const assignedUserId = ticket.assignedTo ?? ticket.createdBy;

  return {
    id: ticket.id,
    ticketId: ticket.ticketNumber,
    title: ticket.title ?? `${TICKET_CASE_TYPE_LABELS[ticket.caseType]} #${ticket.ticketNumber}`,
    dueDate: formatTicketShortDate(ticket.createdAt),
    comments: ticket.notes ? 1 : 0,
    links: 1,
    assigneeInitials: getTicketAssigneeInitials(assignedUserId),
    status: ticket.status,
    priority: ticket.priority,
    description: getTicketDescription(ticket),
    category,
    organizationId: ticket.organizationId,
    createdBy: ticket.createdBy,
    assignedTo: ticket.assignedTo,
    notes: ticket.notes,
    resolvedAt: ticket.resolvedAt,
    closedAt: ticket.closedAt,
    createdAt: ticket.createdAt,
  };
};

// La cuenta de una columna del kanban es el mismo estado que el badge de un
// ticket individual, solo que se muestra en otro lugar de la UI -- de ahí que
// compartan el mismo mapeo de colores.
const CATEGORY_BADGE_COLOR: Record<string, BadgeColor> = {
  brand: "primary",
  error: "error",
};

export const getCategoryBadgeColor = (color: string): BadgeColor => CATEGORY_BADGE_COLOR[color] ?? "light";

const STATUS_BADGE_COLOR: Record<SupportTicketStatus, BadgeColor> = {
  NUEVO: "primary",
  ABIERTO: "light",
  EN_PROGRESO: "warning",
  PENDIENTE_CLIENTE: "warning",
  PENDIENTE_TERCERO: "warning",
  RESUELTO: "success",
  CERRADO: "dark",
};

export const getStatusBadgeColor = (status: SupportTicketStatus): BadgeColor => STATUS_BADGE_COLOR[status] ?? "light";

const PRIORITY_BADGE_COLOR: Record<SupportTicketPriority, BadgeColor> = {
  URGENTE: "error",
  ALTA: "warning",
  MEDIA: "info",
  BAJA: "light",
};

export const getPriorityBadgeColor = (priority: SupportTicketPriority): BadgeColor => PRIORITY_BADGE_COLOR[priority] ?? "light";

export const formatTicketDetailDate = (iso: string | null): string =>
  formatDateTimeLong(iso, "Pendiente");

const formatTicketShortDate = (iso: string): string => {
  const date = new Date(iso);
  const today = new Date();

  if (
    date.getFullYear() === today.getFullYear() &&
    date.getMonth() === today.getMonth() &&
    date.getDate() === today.getDate()
  ) {
    return "Hoy";
  }

  return date.toLocaleDateString("es-CO", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
};

const getTicketCategory = (caseType: SupportCaseType): TicketKanbanCategory => {
  switch (caseType) {
    case "REQUERIMIENTO":
      return { name: "Requerimiento", color: "brand" };
    case "INCIDENTE":
      return { name: "Incidente", color: "error" };
    default:
      return { name: "Soporte", color: "default" };
  }
};

const getTicketDescription = (ticket: SupportTicket): string => {
  if (ticket.notes) return ticket.notes;

  if (ticket.topic === "VALIDACION_DOCUMENTO") {
    return `Solicitud de revisión documental para la entidad ${ticket.organizationId}.`;
  }

  return `Caso creado por el usuario ${ticket.createdBy}.`;
};

const getTicketAssigneeInitials = (userId: string): string =>
  `U${userId}`.slice(0, 3).toUpperCase();
