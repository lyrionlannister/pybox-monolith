import type { FinancialInstitution } from "@/credits/types/wompi-checkout-types";

export interface PseFieldsValue {
  userType: "0" | "1";
  userLegalIdType: string;
  userLegalId: string;
  financialInstitutionCode: string;
  paymentDescription: string;
  // Wompi los ignora; PayU y ePayco los exigen para PSE.
  fullName: string;
  phone: string;
  address: string;
  city: string;
}

export interface WompiPseFieldsProps {
  value: PseFieldsValue;
  onChange: (value: PseFieldsValue) => void;
  institutions: FinancialInstitution[];
  loadingInstitutions: boolean;
}
