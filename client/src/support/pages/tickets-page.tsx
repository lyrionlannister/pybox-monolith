import { useCallback, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { LayoutList, Kanban, Plus, Search, X, Inbox } from "lucide-react";
import { Breadcrumb } from "@/ui/components/common/breadcrumb";
import { Loader } from "@/ui/components/loader/loader";
import EmptyState from "@/ui/components/common/empty-state";
import { Select } from "@/ui/components/inputs/select";
import { Button } from "@/ui/components/button/button";
import { useTickets } from "@/support/hooks/use-tickets";
import { useTicketMetrics } from "@/support/hooks/use-ticket-metrics";
import { useTicketPermissions } from "@/support/hooks/use-ticket-permissions";
import { useUpdateTicketStatus } from "@/support/hooks/use-update-ticket-status";
import { TicketKanbanHeader } from "@/support/components/ticket-kanban/ticket-kanban-header";
import { TicketKanbanBoard } from "@/support/components/ticket-kanban/ticket-kanban-board";
import { TicketListItem } from "@/support/components/ticket-list/ticket-list-item";
import { MetricCard } from "@/support/components/metric-card";
import { getTicketKanbanGroups, mapTicketToKanban, TICKET_STATUS_LABELS, TICKET_PRIORITY_LABELS } from "@/support/utils/ticket-kanban-utils";
import type { SupportTicket, SupportTicketPriority, SupportTicketStatus, TicketFilterParams } from "@/types/support/support-types";
import type { TicketKanbanGroupKey } from "@/types/support/ticket-kanban-types";
import type { DateGroup } from "@/support/types/date-group";
import { TICKET_FILTER_STATUSES as STATUSES, TICKET_FILTER_PRIORITIES as PRIORITIES } from "@/support/constants/ticket-filter-options";

function groupByDate(tickets: SupportTicket[]): DateGroup[] {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfYesterday = new Date(startOfToday);
  startOfYesterday.setDate(startOfYesterday.getDate() - 1);
  const startOfWeek = new Date(startOfToday);
  startOfWeek.setDate(startOfWeek.getDate() - 7);

  const groups: DateGroup[] = [
    { label: "Hoy", tickets: [] },
    { label: "Ayer", tickets: [] },
    { label: "Esta semana", tickets: [] },
    { label: "Anteriores", tickets: [] },
  ];

  for (const ticket of tickets) {
    const d = new Date(ticket.createdAt);
    const startOfDay = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    if (startOfDay.getTime() === startOfToday.getTime()) groups[0].tickets.push(ticket);
    else if (startOfDay.getTime() === startOfYesterday.getTime()) groups[1].tickets.push(ticket);
    else if (startOfDay >= startOfWeek) groups[2].tickets.push(ticket);
    else groups[3].tickets.push(ticket);
  }

  return groups.filter((g) => g.tickets.length > 0);
}

type ViewMode = "list" | "kanban";

export const TicketsPage: React.FC = () => {
  const navigate = useNavigate();
  const [selectedGroup, setSelectedGroup] = useState<TicketKanbanGroupKey>("all");
  const [filters, setFilters] = useState<TicketFilterParams>({ includeResolved: true });
  const [searchInput, setSearchInput] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("list");

  const { tickets, loading, refetch } = useTickets(filters);
  const { metrics } = useTicketMetrics();
  const { canCreate } = useTicketPermissions();
  const { updateStatus } = useUpdateTicketStatus();

  const handleStatusChange = useCallback(
    async (ticketNumber: number, newStatus: SupportTicketStatus): Promise<boolean> => {
      const ok = await updateStatus(ticketNumber, newStatus);
      if (ok) refetch();
      return ok;
    },
    [updateStatus, refetch],
  );

  const applySearch = () => {
    setFilters((f) => ({ ...f, q: searchInput.trim() || undefined }));
  };

  const clearSearch = () => {
    setSearchInput("");
    setFilters((f) => ({ ...f, q: undefined }));
  };

  const setFilter = <K extends keyof TicketFilterParams>(key: K, val: TicketFilterParams[K]) => {
    setFilters((f) => ({ ...f, [key]: val || undefined }));
  };

  const hasActiveFilters = !!(filters.q || filters.status || filters.priority);

  const filtered = useMemo(() => {
    if (selectedGroup === "all") return tickets;
    return tickets.filter((t) => t.status === selectedGroup);
  }, [tickets, selectedGroup]);

  const kanbanTickets = useMemo(() => tickets.map(mapTicketToKanban), [tickets]);
  const dateGroups = useMemo(() => groupByDate(filtered), [filtered]);
  const groups = useMemo(() => getTicketKanbanGroups(kanbanTickets), [kanbanTickets]);

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-hidden">
      <div className="flex items-center justify-between">
        <Breadcrumb pageTitle="Tickets" />
        {canCreate && (
          <Button type="button" size="sm" startIcon={<Plus size={15} />} onClick={() => navigate("/cs/tickets/new")}>
            Nuevo ticket
          </Button>
        )}
      </div>

      {metrics && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
          <MetricCard label="Total" value={metrics.total} />
          <MetricCard label="Abiertos" value={metrics.open} accent="text-brand-600 dark:text-brand-400" />
          <MetricCard label="En proceso" value={metrics.inProgress} accent="text-warning-600 dark:text-warning-400" />
          <MetricCard label="Pendientes" value={metrics.pending} accent="text-orange-600 dark:text-orange-400" />
          <MetricCard label="Resueltos" value={metrics.resolved} accent="text-success-600 dark:text-success-400" />
          <MetricCard label="Hoy creados" value={metrics.createdToday} />
          <MetricCard
            label="Prom. resolución"
            value={metrics.avgResolutionHours != null ? `${metrics.avgResolutionHours}h` : "—"}
          />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-48">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && applySearch()}
            placeholder="Buscar por título o descripción..."
            className="w-full rounded-lg border border-gray-200 bg-white py-1.5 pl-8 pr-8 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-brand-300 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300 dark:placeholder:text-gray-600"
          />
          {searchInput && (
            <button type="button" onClick={clearSearch} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
              <X size={13} />
            </button>
          )}
        </div>

        <div className="w-44">
          <Select
            placeholder="Todos los estados"
            value={filters.status ?? ""}
            onChange={(v) => setFilter("status", v as SupportTicketStatus)}
            options={STATUSES.map((s) => ({ value: s, label: TICKET_STATUS_LABELS[s] }))}
          />
        </div>

        <div className="w-48">
          <Select
            placeholder="Todas las prioridades"
            value={filters.priority ?? ""}
            onChange={(v) => setFilter("priority", v as SupportTicketPriority)}
            options={PRIORITIES.map((p) => ({ value: p, label: TICKET_PRIORITY_LABELS[p] }))}
          />
        </div>

        {hasActiveFilters && (
          <button
            type="button"
            onClick={() => { clearSearch(); setFilters({ includeResolved: true }); }}
            className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-400 dark:hover:bg-white/5"
          >
            <X size={12} /> Limpiar
          </button>
        )}

        <div className="ml-auto flex items-center rounded-lg border border-gray-200 dark:border-gray-700">
          <button
            type="button"
            onClick={() => setViewMode("list")}
            title="Vista lista"
            className={`rounded-l-lg px-3 py-1.5 transition-colors ${viewMode === "list" ? "bg-brand-500 text-white" : "text-gray-500 hover:bg-gray-50 dark:text-gray-400 dark:hover:bg-white/5"}`}
          >
            <LayoutList size={15} />
          </button>
          <button
            type="button"
            onClick={() => setViewMode("kanban")}
            title="Vista kanban"
            className={`rounded-r-lg px-3 py-1.5 transition-colors ${viewMode === "kanban" ? "bg-brand-500 text-white" : "text-gray-500 hover:bg-gray-50 dark:text-gray-400 dark:hover:bg-white/5"}`}
          >
            <Kanban size={15} />
          </button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto custom-scrollbar rounded-2xl border border-gray-200 bg-white dark:border-gray-800 dark:bg-white/3">
        <TicketKanbanHeader
          groups={groups}
          selectedGroup={selectedGroup}
          onSelectGroup={setSelectedGroup}
        />

        {loading ? (
          <div className="flex min-h-60 items-center justify-center border-t border-gray-200 dark:border-white/5">
            <Loader loaderText="Cargando tickets..." />
          </div>
        ) : viewMode === "kanban" ? (
          <TicketKanbanBoard
            tickets={kanbanTickets}
            selectedGroup={selectedGroup}
            onOpenTicket={(n) => navigate(`/cs/tickets/${n}`)}
            onStatusChange={handleStatusChange}
          />
        ) : dateGroups.length === 0 ? (
          <div className="flex min-h-60 items-center justify-center border-t border-gray-200 dark:border-white/5">
            <EmptyState icon={Inbox} title="No hay tickets" />
          </div>
        ) : (
          <div className="border-t border-gray-200 dark:border-white/5">
            {dateGroups.map((group) => (
              <div key={group.label}>
                <div className="flex items-center gap-2 px-4 py-3">
                  <span className="text-sm font-medium text-gray-800 dark:text-white/90">{group.label}</span>
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600 dark:bg-white/5 dark:text-gray-400">
                    {group.tickets.length}
                  </span>
                </div>
                {group.tickets.map((ticket) => (
                  <TicketListItem
                    key={ticket.id}
                    ticket={ticket}
                    onClick={() => navigate(`/cs/tickets/${ticket.ticketNumber}`)}
                  />
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
