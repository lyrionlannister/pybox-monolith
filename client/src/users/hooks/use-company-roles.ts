import { useCallback, useState } from "react";
import { useApiClient } from "@/hooks/use-api-client";
import { useAsyncResource } from "@/hooks/use-async-resource";
import type {
  CompanyRole,
  CompanyRoleCreatePayload,
  CompanyRoleUpdatePayload,
} from "@/users/types/company-role-types";

export const useCompanyRoles = (orgId: string) => {
  const { apiClient } = useApiClient();
  const [saving, setSaving] = useState(false);

  const fetchRoles = useCallback(() => {
    if (!orgId) return Promise.resolve([]);
    return apiClient(`/organizations/${orgId}/company-roles`, { method: "GET" }) as Promise<CompanyRole[]>;
  }, [orgId, apiClient]);

  const { data: roles, loading, error, refetch, setData: setRoles } = useAsyncResource<CompanyRole[]>(
    fetchRoles,
    [],
    [orgId],
  );

  const create = async (payload: CompanyRoleCreatePayload): Promise<CompanyRole | null> => {
    setSaving(true);
    try {
      const created: CompanyRole = await apiClient(`/organizations/${orgId}/company-roles`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setRoles((prev) => [...prev, created]);
      return created;
    } catch {
      return null;
    } finally {
      setSaving(false);
    }
  };

  const update = async (
    roleId: string,
    payload: CompanyRoleUpdatePayload,
  ): Promise<CompanyRole | null> => {
    setSaving(true);
    try {
      const updated: CompanyRole = await apiClient(`/organizations/${orgId}/company-roles/${roleId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      setRoles((prev) => prev.map((r) => (r.id === roleId ? updated : r)));
      return updated;
    } catch {
      return null;
    } finally {
      setSaving(false);
    }
  };

  const remove = async (roleId: string): Promise<boolean> => {
    setSaving(true);
    try {
      await apiClient(`/organizations/${orgId}/company-roles/${roleId}`, { method: "DELETE" });
      setRoles((prev) => prev.filter((r) => r.id !== roleId));
      return true;
    } catch {
      return false;
    } finally {
      setSaving(false);
    }
  };

  return { roles, loading, error, saving, refetch, create, update, remove };
};
