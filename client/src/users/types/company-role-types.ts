export interface CompanyRole {
  id: string;
  name: string;
  description: string | null;
  isActive: boolean;
  permissionNames: string[];
}

export interface CompanyRoleCreatePayload {
  name: string;
  description?: string | null;
  permissionNames: string[];
}

export interface CompanyRoleUpdatePayload {
  name?: string;
  description?: string | null;
  isActive?: boolean;
  permissionNames?: string[];
}
