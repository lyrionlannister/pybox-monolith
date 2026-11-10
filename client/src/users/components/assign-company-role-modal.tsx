import { useEffect, useState } from "react";
import { Users } from "lucide-react";
import { useApiClient } from "@/hooks/use-api-client";
import { Modal } from "@/ui/components/modal/modal";
import { Button } from "@/ui/components/button/button";
import { Loader } from "@/ui/components/loader/loader";
import EmptyState from "@/ui/components/common/empty-state";
import { useUsers } from "../hooks/use-users";
import { CheckItem } from "./check-item";
import type { CompanyRole } from "@/users/types/company-role-types";

interface AssignCompanyRoleModalProps {
  isOpen: boolean;
  onClose: () => void;
  orgId: string;
  role: CompanyRole | null;
}

export const AssignCompanyRoleModal: React.FC<AssignCompanyRoleModalProps> = ({
  isOpen,
  onClose,
  orgId,
  role,
}) => {
  const { apiClient } = useApiClient();
  const { users, loading: usersLoading } = useUsers(orgId);
  const [assigned, setAssigned] = useState<Set<string>>(new Set());
  const [loadingAssigned, setLoadingAssigned] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen || !role) return;
    setLoadingAssigned(true);
    apiClient<string[]>(`/organizations/${orgId}/company-roles/${role.id}/users`)
      .then((ids) => setAssigned(new Set(ids)))
      .catch(() => setAssigned(new Set()))
      .finally(() => setLoadingAssigned(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, role?.id]);

  const toggle = async (userId: string, checked: boolean) => {
    if (!role) return;
    setBusy(userId);
    const url = `/organizations/${orgId}/company-roles/${role.id}/users/${userId}`;
    const ok = await apiClient(url, { method: checked ? "POST" : "DELETE" })
      .then(() => true)
      .catch(() => false);
    if (ok) {
      setAssigned((prev) => {
        const next = new Set(prev);
        if (checked) next.add(userId);
        else next.delete(userId);
        return next;
      });
    }
    setBusy(null);
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} className="max-w-md p-6" ariaLabel="Miembros del rol">
      <h3 className="mb-4 text-lg font-semibold text-gray-800 dark:text-white/90">
        Miembros de {role?.name}
      </h3>

      <div className="max-h-80 overflow-y-auto custom-scrollbar rounded-lg border border-gray-200 dark:border-gray-800">
        <ul className="flex flex-col">
          {usersLoading || loadingAssigned ? (
            <li className="px-4 py-4"><Loader size="sm" loaderText="Cargando..." /></li>
          ) : users.length === 0 ? (
            <li className="px-4 py-5"><EmptyState icon={Users} title="Sin miembros en esta empresa" /></li>
          ) : (
            users.map((u) => (
              <CheckItem
                key={u.id}
                id={`role-member-${u.id}`}
                label={u.fullName}
                sublabel={u.email}
                checked={assigned.has(u.id)}
                busy={busy === u.id}
                onChange={(checked) => toggle(u.id, checked)}
              />
            ))
          )}
        </ul>
      </div>

      <div className="mt-5 flex justify-end">
        <Button variant="outline" onClick={onClose}>Cerrar</Button>
      </div>
    </Modal>
  );
};
