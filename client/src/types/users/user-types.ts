export interface RoleEntry {
  role: string;
  scope: string;
  orgId: string | null;
  orgName: string | null;
}

export interface UserSummary {
  id: string;
  fullName: string;
  email: string;
  phoneNumber: string | null;
  isActive: boolean;
  createdAt: string | null;
  /** Solo viene poblado cuando lo pide un Admin Global con includeDeleted=true. */
  deletedAt: string | null;
  roles: RoleEntry[];
}

export interface UserDetail extends UserSummary {
  firstname: string;
  lastname: string;
  phoneNumber: string | null;
  authProvider: string;
  documentType: string | null;
  documentNumber: string | null;
  isEmailVerified: boolean;
  isPhoneVerified: boolean;
  mfaEnabled: boolean;
  isActiveSessions: boolean;
  updatedAt: string | null;
  profilePhotoUrl: string | null;
}

export interface UpdateUserPayload {
  firstname?: string;
  lastname?: string;
  email?: string;
  phoneNumber?: string;
  isActive?: boolean;
  documentType?: string;
  documentNumber?: string;
  mfaEnabled?: boolean;
  /** Obligatoria cuando el propio usuario cambia su correo o desactiva su MFA. */
  currentPassword?: string;
}
