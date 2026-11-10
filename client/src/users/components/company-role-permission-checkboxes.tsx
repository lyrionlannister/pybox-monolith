import { ShieldOff } from "lucide-react";
import { Loader } from "@/ui/components/loader/loader";
import EmptyState from "@/ui/components/common/empty-state";
import type { PermissionCatalogEntry } from "@/types/users/permission-types";

interface CompanyRolePermissionCheckboxesProps {
  catalog: PermissionCatalogEntry[];
  loading: boolean;
  selected: string[];
  onToggle: (name: string, checked: boolean) => void;
}

export const CompanyRolePermissionCheckboxes: React.FC<CompanyRolePermissionCheckboxesProps> = ({
  catalog,
  loading,
  selected,
  onToggle,
}) => {
  if (loading) return <Loader size="sm" loaderText="Cargando permisos..." />;
  if (catalog.length === 0)
    return <EmptyState icon={ShieldOff} title="No hay permisos configurados" className="py-4" />;

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {catalog.map((perm) => {
        const checked = selected.includes(perm.name);
        return (
          <label
            key={perm.name}
            className="flex items-start gap-3 rounded-lg border border-gray-200 p-3 cursor-pointer hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-white/5"
          >
            <input
              type="checkbox"
              checked={checked}
              onChange={(e) => onToggle(perm.name, e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-gray-300 text-brand-500 focus:ring-brand-500 dark:border-gray-700"
            />
            <span>
              <span className="block text-sm font-medium text-gray-800 dark:text-white/90">
                {perm.label ?? perm.name}
              </span>
              {perm.description && (
                <span className="block text-xs text-gray-400 dark:text-gray-500 mt-0.5">
                  {perm.description}
                </span>
              )}
            </span>
          </label>
        );
      })}
    </div>
  );
};
