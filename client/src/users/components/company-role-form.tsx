import { Input } from "@/ui/components/inputs/input";
import { Switch } from "@/ui/components/switch";
import { Button } from "@/ui/components/button/button";
import type { PermissionCatalogEntry } from "@/types/users/permission-types";
import { CompanyRolePermissionCheckboxes } from "./company-role-permission-checkboxes";

interface CompanyRoleFormProps {
  editingId: string | null;
  name: string;
  onChangeName: (value: string) => void;
  description: string;
  onChangeDescription: (value: string) => void;
  isActive: boolean;
  onChangeIsActive: (value: boolean) => void;
  catalog: PermissionCatalogEntry[];
  catalogLoading: boolean;
  selectedPermissions: string[];
  onTogglePermission: (name: string, checked: boolean) => void;
  saving: boolean;
  onSave: () => void;
  onCancelEdit: () => void;
}

export const CompanyRoleForm: React.FC<CompanyRoleFormProps> = ({
  editingId,
  name,
  onChangeName,
  description,
  onChangeDescription,
  isActive,
  onChangeIsActive,
  catalog,
  catalogLoading,
  selectedPermissions,
  onTogglePermission,
  saving,
  onSave,
  onCancelEdit,
}) => {
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave();
  };

  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-white/3">
      <h2 className="mb-4 text-base font-medium text-gray-800 dark:text-white/90">
        {editingId ? "Editar rol" : "Crear rol de empresa"}
      </h2>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Input
            label="Nombre"
            value={name}
            onChange={(e) => onChangeName(e.target.value)}
            maxLength={100}
          />
          <Input
            label="Descripción"
            value={description}
            onChange={(e) => onChangeDescription(e.target.value)}
            maxLength={500}
          />
        </div>

        <div>
          <span className="mb-2 block text-sm text-gray-600 dark:text-gray-400">Permisos</span>
          <CompanyRolePermissionCheckboxes
            catalog={catalog}
            loading={catalogLoading}
            selected={selectedPermissions}
            onToggle={onTogglePermission}
          />
        </div>

        <div className="mt-2 flex items-center justify-between">
          {editingId ? (
            <Switch checked={isActive} onChange={onChangeIsActive} label="Activo" />
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            {editingId && (
              <Button type="button" size="sm" variant="outline" onClick={onCancelEdit}>
                Cancelar
              </Button>
            )}
            <Button type="submit" size="sm" disabled={!name.trim()} loading={saving} loadingText="Guardando…">
              Guardar
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
};
