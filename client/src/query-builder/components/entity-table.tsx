import { Edit2, Play, Trash2, History, ClipboardList } from "lucide-react";
import EmptyState from "@/ui/components/common/empty-state";
import { Loader } from "@/ui/components/loader/loader";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/ui/components/table/table";
import { PaginationWithIcon } from "@/ui/components/table/pagination-with-icon";
import { getMainTableLabel } from "@/query-builder/utils/get-main-table-label";
import type { EntityTableProps, ActionBtnProps } from "@/query-builder/types/entity-table-props";

export const EntityTable: React.FC<EntityTableProps> = ({
  config,
  entities,
  loading,
  total,
  page,
  pages,
  onEdit,
  onExecute,
  onHistory,
  onDelete,
  onPageChange,
}) => {
  if (loading) {
    return (
      <div className="flex flex-1 min-h-0 items-center justify-center">
        <Loader />
      </div>
    );
  }

  if (entities.length === 0) {
    return (
      <div className="flex flex-1 min-h-0 items-center justify-center">
        <EmptyState icon={ClipboardList} title={`No hay ${config.copy.entityNounPlural}. Crea el primero.`} />
      </div>
    );
  }

  return (
    <div className="flex flex-1 min-h-0 flex-col">
      <div className="hidden flex-1 min-h-0 flex-col overflow-hidden rounded-2xl border border-gray-200 dark:border-gray-800 sm:flex">
        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
          <Table>
            <TableHeader>
              <TableRow className="border-b border-gray-200 bg-gray-50 dark:border-gray-800 dark:bg-white/3">
                {["ID", "Nombre", "Tabla principal", "Descripción", ""].map((h, i) => (
                  <TableCell
                    key={i}
                    isHeader
                    className="px-5 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400"
                  >
                    {h}
                  </TableCell>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody className="divide-y divide-gray-100 dark:divide-gray-800">
              {entities.map((e) => (
                <TableRow key={e.id} className="transition hover:bg-gray-50 dark:hover:bg-white/3">
                  <TableCell className="px-5 py-4 text-sm font-mono text-gray-400">
                    {e.id}
                  </TableCell>
                  <TableCell className="px-5 py-4 text-sm font-medium text-gray-800 dark:text-white/90">
                    {e.name}
                  </TableCell>
                  <TableCell className="px-5 py-4 text-sm text-gray-600 dark:text-gray-400">
                    {getMainTableLabel(e.config, config.allTables)}
                  </TableCell>
                  <TableCell className="px-5 py-4 text-sm text-gray-500 dark:text-gray-400 max-w-xs truncate">
                    {e.description ?? "—"}
                  </TableCell>
                  <TableCell className="px-5 py-4">
                    <div className="flex items-center gap-1">
                      <ActionBtn title="Ejecutar" onClick={() => onExecute(e)} icon={<Play size={16} />} />
                      <ActionBtn title="Historial" onClick={() => onHistory(e)} icon={<History size={16} />} />
                      <ActionBtn title="Editar" onClick={() => onEdit(e)} icon={<Edit2 size={16} />} />
                      <ActionBtn title="Eliminar" onClick={() => onDelete(e)} icon={<Trash2 size={16} />} danger />
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>

      <div className="flex flex-1 min-h-0 flex-col gap-3 overflow-y-auto sm:hidden">
        {entities.map((e) => (
          <div
            key={e.id}
            className="rounded-2xl border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900"
          >
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="font-medium text-gray-800 dark:text-white/90">{e.name}</p>
                <p className="mt-0.5 text-xs text-gray-400">
                  {getMainTableLabel(e.config, config.allTables)}
                </p>
                {e.description && (
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400 line-clamp-2">
                    {e.description}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <ActionBtn title="Ejecutar" onClick={() => onExecute(e)} icon={<Play size={15} />} />
                <ActionBtn title="Historial" onClick={() => onHistory(e)} icon={<History size={15} />} />
                <ActionBtn title="Editar" onClick={() => onEdit(e)} icon={<Edit2 size={15} />} />
                <ActionBtn title="Eliminar" onClick={() => onDelete(e)} icon={<Trash2 size={15} />} danger />
              </div>
            </div>
          </div>
        ))}
      </div>

      {pages > 1 && (
        <div className="mt-4 flex flex-col gap-2 border-t border-gray-100 pt-4 dark:border-gray-800 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Página {page} de {pages} · {total} {config.copy.entityNoun}{total !== 1 ? "s" : ""}
          </p>
          <PaginationWithIcon key={page} totalPages={pages} initialPage={page} onPageChange={onPageChange} />
        </div>
      )}
    </div>
  );
};

const ActionBtn: React.FC<ActionBtnProps> = ({ title, onClick, icon, danger }) => (
  <button
    type="button"
    title={title}
    aria-label={title}
    onClick={onClick}
    className={`rounded-lg p-1.5 transition-all ${
      danger
        ? "text-gray-400 hover:bg-red-50 hover:text-red-500 dark:text-gray-500 dark:hover:bg-red-500/10 dark:hover:text-red-400"
        : "text-gray-400 hover:bg-brand-50 hover:text-brand-600 dark:text-gray-500 dark:hover:bg-brand-500/10 dark:hover:text-brand-400"
    }`}
  >
    {icon}
  </button>
);
