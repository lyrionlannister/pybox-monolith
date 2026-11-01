import { KeyRound, Pencil, Trash2 } from "lucide-react";
import EmptyState from "@/ui/components/common/empty-state";
import { Loader } from "@/ui/components/loader/loader";
import { Badge } from "@/ui/components/badge";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/ui/components/table/table";
import { PROVIDER_FIELD_SPECS } from "@/messaging-credentials/constants/provider-field-specs";
import type { CredentialsTableProps } from "@/messaging-credentials/types/props/credentials-table-props";

const SecretChips: React.FC<{ secretKeys: string[] }> = ({ secretKeys }) =>
  secretKeys.length === 0 ? (
    <span className="text-gray-400">—</span>
  ) : (
    <div className="flex flex-wrap gap-1">
      {secretKeys.map((k) => (
        <span
          key={k}
          className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600 dark:bg-white/10 dark:text-gray-300"
        >
          {k} ✓
        </span>
      ))}
    </div>
  );

export const CredentialsTable: React.FC<CredentialsTableProps> = ({ items, loading, countryLabel, onEdit, onDelete }) => (
  <div className="flex flex-1 min-h-0 flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-gray-800 dark:bg-white/3">
    <div className="hidden overflow-x-auto custom-scrollbar sm:block">
      <Table>
        <TableHeader>
          <TableRow className="border-b border-gray-200 bg-gray-50 dark:border-gray-800 dark:bg-white/3">
            <TableCell isHeader className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400">Proveedor</TableCell>
            <TableCell isHeader className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400">País</TableCell>
            <TableCell isHeader className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400">Secretos</TableCell>
            <TableCell isHeader className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400">Estado</TableCell>
            <TableCell isHeader className="px-4 py-3">{""}</TableCell>
          </TableRow>
        </TableHeader>
        <TableBody className="divide-y divide-gray-100 dark:divide-gray-800">
          {loading ? (
            <TableRow>
              <TableCell className="px-4 py-10 text-center" colSpan={5}>
                <Loader size="sm" loaderText="Cargando..." />
              </TableCell>
            </TableRow>
          ) : items.length === 0 ? (
            <TableRow>
              <TableCell className="px-4 py-10 text-center" colSpan={5}>
                <EmptyState icon={KeyRound} title="Sin credenciales configuradas" />
              </TableCell>
            </TableRow>
          ) : (
            items.map((row) => (
              <TableRow key={row.id} className="hover:bg-gray-50 dark:hover:bg-white/3">
                <TableCell className="px-4 py-3 text-sm text-gray-800 dark:text-white/90">
                  {PROVIDER_FIELD_SPECS[row.provider]?.label ?? row.provider}
                </TableCell>
                <TableCell className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">{countryLabel(row.countryCode)}</TableCell>
                <TableCell className="px-4 py-3">
                  <SecretChips secretKeys={row.secretKeys} />
                </TableCell>
                <TableCell className="px-4 py-3">
                  <Badge color={row.isActive ? "success" : "light"} variant="light" size="sm">
                    {row.isActive ? "Activa" : "Inactiva"}
                  </Badge>
                </TableCell>
                <TableCell className="px-4 py-3">
                  <div className="flex justify-end gap-1">
                    <button type="button" onClick={() => onEdit(row)} title="Editar" aria-label="Editar" className="rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-800">
                      <Pencil size={14} />
                    </button>
                    <button type="button" onClick={() => onDelete(row)} title="Eliminar" aria-label="Eliminar" className="rounded p-1.5 text-gray-400 hover:bg-error-50 hover:text-error-500">
                      <Trash2 size={14} />
                    </button>
                  </div>
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
        <EmptyState icon={KeyRound} title="Sin credenciales configuradas" className="py-10" />
      ) : (
        items.map((row) => (
          <div
            key={row.id}
            className="w-full rounded-2xl border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900"
          >
            <div className="flex items-start justify-between gap-2">
              <p className="font-medium text-gray-800 dark:text-white/90">
                {PROVIDER_FIELD_SPECS[row.provider]?.label ?? row.provider}
              </p>
              <Badge color={row.isActive ? "success" : "light"} variant="light" size="sm">
                {row.isActive ? "Activa" : "Inactiva"}
              </Badge>
            </div>
            <p className="mt-1 text-xs text-gray-400">{countryLabel(row.countryCode)}</p>
            <div className="mt-2">
              <SecretChips secretKeys={row.secretKeys} />
            </div>
            <div className="mt-3 flex justify-end gap-1 border-t border-gray-100 pt-2 dark:border-gray-800">
              <button type="button" onClick={() => onEdit(row)} title="Editar" aria-label="Editar" className="rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-800">
                <Pencil size={14} />
              </button>
              <button type="button" onClick={() => onDelete(row)} title="Eliminar" aria-label="Eliminar" className="rounded p-1.5 text-gray-400 hover:bg-error-50 hover:text-error-500">
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ))
      )}
    </div>
  </div>
);
