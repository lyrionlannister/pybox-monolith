import { ORG_TOUR_KEY } from "@/companies/constants/org-tour";
import { PORTFOLIOS_LIST_TOUR_KEY } from "@/companies/constants/portfolios-list-tour";
import { PORTFOLIO_MODULES_TOUR_KEY } from "@/companies/constants/portfolio-modules-tour";
import { COMMUNICATIONS_TOUR_KEY } from "@/companies/constants/communications-tour";
import { PROFILE_PHOTO_TOUR_KEY } from "@/profile/constants/profile-photo-tour";

/**
 * Espejo de api/src/identity/users/constants/tour_keys.py — el backend rechaza
 * cualquier clave fuera de este catálogo.
 */
export const TOUR_KEYS = [
  ORG_TOUR_KEY,
  PORTFOLIOS_LIST_TOUR_KEY,
  PORTFOLIO_MODULES_TOUR_KEY,
  COMMUNICATIONS_TOUR_KEY,
  PROFILE_PHOTO_TOUR_KEY,
] as const;
