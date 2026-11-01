import { Activity, BarChart3, Pause, Pencil, Play, Trash2, Megaphone, Search } from "lucide-react";
import EmptyState from "@/ui/components/common/empty-state";
import { Loader } from "@/ui/components/loader/loader";
import { Badge } from "@/ui/components/badge";
import { ChannelBadge } from "@/ui/components/channel-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableRow,
} from "@/ui/components/table/table";
import { PaginationWithIcon } from "@/ui/components/table/pagination-with-icon";
import { SortIcon } from "@/ui/components/table/sort-icon";
import { Select } from "@/ui/components/inputs/select";
import type { CampaignsTableProps } from "@/campaigns/types/campaigns-table-props";
import type { CampaignSortKey } from "@/campaigns/hooks/use-campaigns";
import { formatSchedule } from "../utils/campaign-utils";
import { CAMPAIGN_STATUS_LABELS as STATUS_LABELS, CAMPAIGN_STATUS_COLORS as STATUS_COLORS } from "../constants/campaign-status-labels";
import { PAGE_SIZE_OPTIONS } from "../constants/table-pagination";

export const CampaignsTable: React.FC<CampaignsTableProps> = ({
  items,
  channels,
  isAdmin,
  saving,
  loading,
  total,
  page,
  pages,
  search,
  pageSize,
  sortKey,
  sortOrder,
  onSearch,
  onPageSizeChange,
  onSort,
  onActivate,
  onPause,
  onEdit,
  onMonitor,
  onResults,
  onDelete,
  onPageChange,
}) => {
  const channelLabelById = new Map(channels.map((c) => [c.id, c.label]));
  // El monitor en vivo solo aplica al canal de llamadas IVR.
  const callChannelIds = new Set(channels.filter((c) => c.name === "CALL").map((c) => c.id));
  const startIndex = (page - 1) * pageSize + 1;
  const endIndex = Math.min(page * pageSize, total);

  const SortableHeader = ({ label, sortable }: { label: string; sortable?: CampaignSortKey }) => (
    <TableCell
      isHeader
      className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400"
    >
      {sortable ? (
        <button
          type="button"
          onClick={() => onSort(sortable)}
          className="flex items-center gap-1.5 select-none"
        >
          {label}
          <SortIcon active={sortKey === sortable} order={sortOrder} />
        </button>
      ) : (
        <div className="flex items-center gap-1.5">{label}</div>
      )}
    </TableCell>
  );

  const rowActions = (item: CampaignsTableProps["items"][number]) => (
    <div className="flex items-center gap-1">
      {isAdmin && (item.status === "BORRADOR" || item.status === "PAUSADA") && (
        <button type="button" onClick={() => onActivate(item.id)} disabled={saving} title="Activar" aria-label="Activar" className="rounded p-1.5 text-gray-400 hover:bg-success-50 hover:text-success-600 disabled:opacity-50">
          <Play size={14} />
        </button>
      )}
      {isAdmin && item.status === "PROGRAMADA" && (
        <button type="button" onClick={() => onPause(item.id)} disabled={saving} title="Pausar" aria-label="Pausar" className="rounded p-1.5 text-gray-400 hover:bg-orange-50 hover:text-orange-600 disabled:opacity-50">
          <Pause size={14} />
        </button>
      )}
      {callChannelIds.has(item.channelId) && (
        <button type="button" onClick={() => onMonitor(item)} title="Monitor en vivo" aria-label="Monitor en vivo" className="rounded p-1.5 text-gray-400 hover:bg-brand-50 hover:text-brand-600 dark:hover:bg-brand-500/15">
          <Activity size={14} />
        </button>
      )}
      {callChannelIds.has(item.channelId) && (
        <button type="button" onClick={() => onResults(item)} title="Resultados" aria-label="Resultados" className="rounded p-1.5 text-gray-400 hover:bg-brand-50 hover:text-brand-600 dark:hover:bg-brand-500/15">
          <BarChart3 size={14} />
        </button>
      )}
      {isAdmin && (item.status === "BORRADOR" || item.status === "PAUSADA") && (
        <button type="button" onClick={() => onEdit(item)} title="Editar" aria-label="Editar" className="rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-800">
          <Pencil size={14} />
        </button>
      )}
      {isAdmin && (
        <button type="button" onClick={() => onDelete(item)} title="Eliminar" aria-label="Eliminar" className="rounded p-1.5 text-gray-400 hover:bg-error-50 hover:text-error-500">
          <Trash2 size={14} />
        </button>
      )}
    </div>
  );

  return (
    <div className="flex flex-1 min-h-0 flex-col overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-white/5 dark:bg-white/3">
      <div className="shrink-0 flex flex-col gap-2 px-4 py-3 border-b border-gray-100 dark:border-white/5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-500 dark:text-gray-400">Mostrar</span>
          <div className="w-20">
            <Select
              value={String(pageSize)}
              onChange={(v) => onPageSizeChange(Number(v))}
              options={PAGE_SIZE_OPTIONS.map((v) => ({ value: String(v), label: String(v) }))}
            />
          </div>
          <span className="text-sm text-gray-500 dark:text-gray-400">entradas</span>
        </div>
        <div className="relative">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none">
            <Search size={15} />
          </span>
          <input
            type="text"
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            placeholder="Buscar campañas..."
            className="h-9 w-full rounded-lg border border-gray-300 bg-transparent py-2 pl-9 pr-4 text-sm text-gray-800 shadow-theme-xs placeholder:text-gray-400 focus:border-brand-300 focus:outline-hidden focus:ring-3 focus:ring-brand-500/10 dark:border-gray-700 dark:bg-gray-900 dark:text-white/90 sm:w-64"
          />
        </div>
      </div>

      <div className="hidden flex-1 min-h-0 overflow-auto custom-scrollbar sm:block">
        <Table>
          <TableHeader>
            <TableRow className="border-b border-gray-200 dark:border-gray-800">
              <SortableHeader label="Nombre" sortable="name" />
              <SortableHeader label="Canal" />
              <SortableHeader label="Estado" sortable="status" />
              <SortableHeader label="Programación" />
              <SortableHeader label="Destinatarios" />
              <SortableHeader label="" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell className="px-4 py-10 text-center" colSpan={6}>
                  <Loader size="sm" loaderText="Cargando..." />
                </TableCell>
              </TableRow>
            ) : items.length === 0 ? (
              <TableRow>
                <TableCell className="px-4 py-10 text-center" colSpan={6}>
                  <EmptyState icon={Megaphone} title={search ? "Sin resultados para esa búsqueda" : "No hay campañas registradas"} />
                </TableCell>
              </TableRow>
            ) : (
              items.map((item) => (
                <TableRow key={item.id} className="border-b border-gray-100 last:border-0 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-white/3">
                  <TableCell className="px-4 py-3">
                    <p className="text-sm font-medium text-gray-800 dark:text-white/90">{item.name}</p>
                    {item.description && (
                      <p className="text-xs text-gray-400 dark:text-gray-500">{item.description}</p>
                    )}
                  </TableCell>
                  <TableCell className="px-4 py-3">
                    <ChannelBadge label={channelLabelById.get(item.channelId) ?? "—"} />
                  </TableCell>
                  <TableCell className="px-4 py-3">
                    <Badge size="sm" color={STATUS_COLORS[item.status]}>{STATUS_LABELS[item.status]}</Badge>
                  </TableCell>
                  <TableCell className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">
                    {formatSchedule(item)}
                  </TableCell>
                  <TableCell className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">
                    {item.totalRecipients}
                  </TableCell>
                  <TableCell className="px-4 py-3">
                    {rowActions(item)}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex flex-1 min-h-0 flex-col gap-3 overflow-y-auto p-4 sm:hidden">
        {loading ? (
          <div className="py-10"><Loader size="sm" /></div>
        ) : items.length === 0 ? (
          <EmptyState
            icon={Megaphone}
            title={search ? "Sin resultados para esa búsqueda" : "No hay campañas registradas"}
            className="py-10"
          />
        ) : (
          items.map((item) => (
            <div
              key={item.id}
              className="w-full rounded-2xl border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="font-medium text-gray-800 dark:text-white/90">{item.name}</p>
                  {item.description && (
                    <p className="mt-0.5 truncate text-xs text-gray-400 dark:text-gray-500">{item.description}</p>
                  )}
                </div>
                <div className="shrink-0">
                  <Badge size="sm" color={STATUS_COLORS[item.status]}>{STATUS_LABELS[item.status]}</Badge>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500 dark:text-gray-400">
                <ChannelBadge label={channelLabelById.get(item.channelId) ?? "—"} />
                <span>{formatSchedule(item)}</span>
                <span>{item.totalRecipients} destinatarios</span>
              </div>
              <div className="mt-3 flex justify-end border-t border-gray-100 pt-2 dark:border-gray-800">
                {rowActions(item)}
              </div>
            </div>
          ))
        )}
      </div>

      <div className="shrink-0 border-t border-gray-100 py-3 px-4 dark:border-white/5">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {total === 0
              ? "Sin resultados"
              : `Mostrando ${startIndex}–${endIndex} de ${total}`}
          </p>
          <PaginationWithIcon key={`${search}-${pageSize}`} totalPages={pages} initialPage={page} onPageChange={onPageChange} />
        </div>
      </div>
    </div>
  );
};
