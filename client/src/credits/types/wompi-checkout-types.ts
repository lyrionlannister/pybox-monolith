export type WompiMethod = "NEQUI" | "PSE" | "CARD" | "BANCOLOMBIA_TRANSFER" | "DAVIPLATA";

export type WompiAttemptStatus = "PENDING" | "APPROVED" | "DECLINED" | "ERROR" | "VOIDED";

export interface FinancialInstitution {
  financialInstitutionCode: string;
  financialInstitutionName: string;
}

export interface ThreeDsChallenge {
  currentStep: string;
  currentStepStatus: string;
  challengeHtml: string;
}

export interface PaymentAttemptResult {
  id: string;
  status: WompiAttemptStatus;
  providerReference: string | null;
  providerTransactionId: string | null;
  chargeMode: string;
}

export interface RedirectAction {
  redirectUrl: string;
  redirectMethod: string;
}

export interface TransactionCreationResult {
  attempt: PaymentAttemptResult;
  threeDsChallenge: ThreeDsChallenge | null;
  redirectAction: RedirectAction | null;
  /** Daviplata (ePayco): el cobro espera el OTP que llega a la app del deudor. */
  otpRequired?: boolean;
}
