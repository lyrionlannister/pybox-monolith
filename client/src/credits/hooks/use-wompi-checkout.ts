import { useState } from "react";
import { useApiClient } from "@/hooks/use-api-client";
import type {
  FinancialInstitution,
  PaymentAttemptResult,
  TransactionCreationResult,
} from "@/credits/types/wompi-checkout-types";

/**
 * Único lugar con HTTP para el checkout de Wompi (reglas de `code-distribution`). El
 * polling en sí (setInterval/cleanup) vive en el componente -- aquí solo se expone la
 * consulta de un tick, igual que el resto del proyecto no tiene un hook de polling
 * genérico.
 */
export const useWompiCheckout = (paymentId: string) => {
  const { apiClient } = useApiClient();
  const [submitting, setSubmitting] = useState(false);
  const [confirmingOtp, setConfirmingOtp] = useState(false);

  const createTransaction = async (
    body: Record<string, unknown>,
  ): Promise<TransactionCreationResult | null> => {
    setSubmitting(true);
    try {
      return await apiClient<TransactionCreationResult>(
        `/credits/payments/${paymentId}/transaction`,
        { method: "POST", body: JSON.stringify(body) },
      );
    } catch {
      return null;
    } finally {
      setSubmitting(false);
    }
  };

  const listPseInstitutions = async (): Promise<FinancialInstitution[]> => {
    try {
      return await apiClient<FinancialInstitution[]>(
        `/credits/payments/${paymentId}/pse/financial-institutions`,
        { method: "GET" },
      );
    } catch {
      return [];
    }
  };

  const fetchAttemptStatus = async (attemptId: string): Promise<PaymentAttemptResult | null> => {
    try {
      return await apiClient<PaymentAttemptResult>(
        `/credits/payments/${paymentId}/transactions/${attemptId}`,
        { method: "GET" },
      );
    } catch {
      return null;
    }
  };

  const confirmDaviplataOtp = async (
    attemptId: string,
    otp: string,
  ): Promise<PaymentAttemptResult | null> => {
    setConfirmingOtp(true);
    try {
      return await apiClient<PaymentAttemptResult>(
        `/credits/payments/${paymentId}/transactions/${attemptId}/daviplata/confirm-otp`,
        { method: "POST", body: JSON.stringify({ otp }) },
      );
    } catch {
      return null;
    } finally {
      setConfirmingOtp(false);
    }
  };

  return {
    createTransaction,
    listPseInstitutions,
    fetchAttemptStatus,
    confirmDaviplataOtp,
    submitting,
    confirmingOtp,
  };
};
