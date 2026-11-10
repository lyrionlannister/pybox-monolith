import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import { useToast } from "@/context/toast-context";
import { ModuleBase } from "@/ui/components/common/module-base";
import { ConfirmModal } from "@/ui/components/modal/confirm-modal";
import { useOrgModule } from "@/companies/hooks/use-org-module";
import { useBreadcrumb } from "@/companies/hooks/use-breadcrumb";
import { useCompanyRoles } from "../hooks/use-company-roles";
import { usePermissionsCatalog } from "../hooks/use-permissions-catalog";
import { CompanyRoleForm } from "../components/company-role-form";
import { CompanyRolesTable } from "../components/company-roles-table";
import { AssignCompanyRoleModal } from "../components/assign-company-role-modal";
import type { CompanyRole } from "@/users/types/company-role-types";

export const CompanyRolesPage: React.FC = () => {
  const { orgId } = useOrgModule();
  const { build } = useBreadcrumb();
  const toast = useToast();
  const { roles, loading, saving, create, update, remove } = useCompanyRoles(orgId);
  const { catalog, loading: catalogLoading } = usePermissionsCatalog();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [selectedPermissions, setSelectedPermissions] = useState<string[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [roleToDelete, setRoleToDelete] = useState<CompanyRole | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [roleForMembers, setRoleForMembers] = useState<CompanyRole | null>(null);

  const resetForm = () => {
    setName("");
    setDescription("");
    setIsActive(true);
    setSelectedPermissions([]);
    setEditingId(null);
  };

  const startEdit = (row: CompanyRole) => {
    setName(row.name);
    setDescription(row.description ?? "");
    setIsActive(row.isActive);
    setSelectedPermissions(row.permissionNames);
    setEditingId(row.id);
  };

  const togglePermission = (perm: string, checked: boolean) => {
    setSelectedPermissions((prev) =>
      checked ? [...prev, perm] : prev.filter((p) => p !== perm),
    );
  };

  const save = async () => {
    if (editingId) {
      const result = await update(editingId, {
        name,
        description: description.trim() || null,
        isActive,
        permissionNames: selectedPermissions,
      });
      if (result) {
        toast.success?.("Rol actualizado");
        resetForm();
      }
      return;
    }
    const result = await create({
      name,
      description: description.trim() || null,
      permissionNames: selectedPermissions,
    });
    if (result) {
      toast.success?.("Rol creado");
      resetForm();
    }
  };

  const confirmDelete = async () => {
    if (!roleToDelete) return;
    setDeleting(true);
    const ok = await remove(roleToDelete.id);
    setDeleting(false);
    if (ok) {
      toast.success?.("Rol eliminado");
      setRoleToDelete(null);
    }
  };

  return (
    <ModuleBase pageTitle="Roles de Empresa" pageIcon={ShieldCheck} breadcrumbItems={build()}>
      <div className="flex flex-col gap-6">
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Define roles con un subconjunto de permisos y asígnalos a los miembros de tu
          empresa, en vez de otorgar permisos uno por uno.
        </p>

        <CompanyRoleForm
          editingId={editingId}
          name={name}
          onChangeName={setName}
          description={description}
          onChangeDescription={setDescription}
          isActive={isActive}
          onChangeIsActive={setIsActive}
          catalog={catalog}
          catalogLoading={catalogLoading}
          selectedPermissions={selectedPermissions}
          onTogglePermission={togglePermission}
          saving={saving}
          onSave={save}
          onCancelEdit={resetForm}
        />

        <CompanyRolesTable
          items={roles}
          loading={loading}
          onEdit={startEdit}
          onDelete={setRoleToDelete}
          onManageMembers={setRoleForMembers}
        />

        <ConfirmModal
          isOpen={!!roleToDelete}
          onClose={() => setRoleToDelete(null)}
          onConfirm={confirmDelete}
          title="Eliminar rol"
          message={
            roleToDelete
              ? `¿Eliminar el rol "${roleToDelete.name}"? Si tiene miembros asignados, primero deberás reasignarlos.`
              : ""
          }
          loading={deleting}
        />

        <AssignCompanyRoleModal
          isOpen={!!roleForMembers}
          onClose={() => setRoleForMembers(null)}
          orgId={orgId}
          role={roleForMembers}
        />
      </div>
    </ModuleBase>
  );
};
