import { Crown, Headphones, Shield, ShieldCheck, User, Users } from "lucide-react";
import type { HierarchyTier } from "@/types/props/profile-meta-card-props";

/**
 * Colores limitados a las 4 familias semánticas del proyecto (brand/success/error/warning),
 * no una paleta propia por rol. Admin (global y de organización) comparten "brand"; soporte
 * comparte "warning"; usuario de organización usa "success"; el titular (SELF) se queda
 * neutro en gris -- la distinción de RANGO se ve por la cantidad de puntos en
 * HierarchyDots (tier), no por tener un color único cada uno.
 */
export const ROLE_HIERARCHY: Record<string, HierarchyTier> = {
  "ADMINISTRADOR|GLOBAL": {
    tier: 1,
    label: "Admin Global",
    icon: <Crown size={13} />,
    badgeColor: "primary",
    containerClass: "bg-brand-50 border border-brand-200 dark:bg-brand-500/10 dark:border-brand-500/30",
    iconClass: "text-brand-600 dark:text-brand-400",
    textClass: "text-brand-700 dark:text-brand-400",
    dotClass: "bg-brand-500",
  },
  "ATENCION AL CLIENTE|GLOBAL": {
    tier: 2,
    label: "Soporte Global",
    icon: <ShieldCheck size={13} />,
    badgeColor: "warning",
    containerClass: "bg-warning-50 border border-warning-200 dark:bg-warning-500/10 dark:border-warning-500/30",
    iconClass: "text-warning-600 dark:text-warning-400",
    textClass: "text-warning-700 dark:text-warning-400",
    dotClass: "bg-warning-500",
  },
  "ADMINISTRADOR|ORGANIZATION": {
    tier: 3,
    label: "Administrador",
    icon: <Shield size={13} />,
    badgeColor: "primary",
    containerClass: "bg-brand-50 border border-brand-200 dark:bg-brand-500/10 dark:border-brand-500/30",
    iconClass: "text-brand-600 dark:text-brand-400",
    textClass: "text-brand-700 dark:text-brand-400",
    dotClass: "bg-brand-500",
  },
  "ATENCION AL CLIENTE|ORGANIZATION": {
    tier: 4,
    label: "Soporte",
    icon: <Headphones size={13} />,
    badgeColor: "warning",
    containerClass: "bg-warning-50 border border-warning-200 dark:bg-warning-500/10 dark:border-warning-500/30",
    iconClass: "text-warning-600 dark:text-warning-400",
    textClass: "text-warning-700 dark:text-warning-400",
    dotClass: "bg-warning-500",
  },
  "USUARIO|ORGANIZATION": {
    tier: 5,
    label: "Usuario",
    icon: <Users size={13} />,
    badgeColor: "success",
    containerClass: "bg-success-50 border border-success-200 dark:bg-success-500/10 dark:border-success-500/30",
    iconClass: "text-success-600 dark:text-success-400",
    textClass: "text-success-700 dark:text-success-400",
    dotClass: "bg-success-500",
  },
  "USUARIO|SELF": {
    tier: 6,
    label: "Usuario",
    icon: <User size={13} />,
    badgeColor: "light",
    containerClass: "bg-gray-100 border border-gray-200 dark:bg-gray-700 dark:border-gray-600",
    iconClass: "text-gray-500 dark:text-gray-400",
    textClass: "text-gray-600 dark:text-gray-400",
    dotClass: "bg-gray-400",
  },
};

export const getRoleHierarchy = (role?: string, scope?: string): HierarchyTier | null => {
  if (!role || !scope) return null;
  return ROLE_HIERARCHY[`${role}|${scope}`] ?? null;
};
