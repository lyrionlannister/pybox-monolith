import { useState } from "react";
import type { FinancialEventDetailsProps } from "@/types/props/financial-event-details-props";
import { STATUS_META } from "@/constants/credits/financial-calendar";
import { PAYMENT_STATUS } from "@/credits/types/credit-types";
import { formatCreditCurrency, formatPaymentDate } from "@/credits/utils/financial-calendar-utils";
import { PaymentMethodCard } from "@/ui/components/calendar/payment-method-card";
import { usePaymentSelfService } from "@/credits/hooks/use-payment-selfservice";
import { WompiCheckoutForm } from "@/credits/components/wompi-checkout/wompi-checkout-form";

const RECEIPT_ACCEPT = ".jpg,.jpeg,.png,.pdf";

const dateOnly = (offsetDays: number): string => {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
};

export const FinancialEventDetails: React.FC<FinancialEventDetailsProps> = ({ event, onClose, onActionDone, entityLabel = "Empresa" }) => {
  const { credit, payment, status } = event;
  const { requestReschedule, requestValidation, submitting } = usePaymentSelfService();

  const [mode, setMode] = useState<"pay" | "reschedule" | "validation" | null>(null);
  const [newDate, setNewDate] = useState("");
  const [files, setFiles] = useState<FileList | null>(null);

  const canManage = event.type === "upcoming" && payment.status === PAYMENT_STATUS.PENDING;

  const finish = (ok: boolean) => {
    if (!ok) return;
    setMode(null);
    onActionDone?.();
    onClose();
  };

  const submitReschedule = async () => {
    if (!newDate) return;
    finish(await requestReschedule(payment.id, newDate));
  };

  const submitValidation = async () => {
    if (!files || files.length === 0) return;
    finish(await requestValidation(payment.id, files));
  };

  return (
    <div className="flex flex-1 min-h-0 flex-col px-2 overflow-y-auto custom-scrollbar">
      <div>
        <h5 className="mb-2 font-semibold text-gray-800 modal-title text-theme-xl dark:text-white/90 lg:text-2xl">
          {credit.creditNumber}
        </h5>
        <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${STATUS_META[status].chipClass}`}>
          {STATUS_META[status].label}
        </span>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
        {credit.organizationName && (
          <div className="sm:col-span-2">
            <p className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">{entityLabel}</p>
            <p className="text-sm text-gray-800 dark:text-white/90">{credit.organizationName}</p>
          </div>
        )}
        <div>
          <p className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">Cuota</p>
          <p className="text-sm text-gray-800 dark:text-white/90">
            #{payment.installmentNumber ?? payment.id}
          </p>
        </div>
        <div>
          <p className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">Valor</p>
          <p className="text-sm font-semibold text-gray-800 dark:text-white/90">
            {formatCreditCurrency(payment.paymentAmount, credit.currencyCode)}
          </p>
        </div>
        <div>
          <p className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">Fecha límite</p>
          <p className="text-sm text-gray-800 dark:text-white/90">{formatPaymentDate(payment.limitPayDate)}</p>
        </div>
        <div>
          <p className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">Fecha de pago</p>
          <p className="text-sm text-gray-800 dark:text-white/90">{formatPaymentDate(payment.paymentDate)}</p>
        </div>
      </div>

      {credit.paymentMethods.length > 0 && (
        <div className="mt-6">
          <p className="mb-3 text-xs font-medium text-gray-500 dark:text-gray-400">
            Métodos de pago aceptados
          </p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {credit.paymentMethods.map((m) => (
              <PaymentMethodCard key={m.id} method={m} />
            ))}
          </div>
        </div>
      )}

      {payment.status !== PAYMENT_STATUS.PENDING && (
        <div className="mt-6 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-700 dark:border-amber-900 dark:bg-amber-900/20 dark:text-amber-300">
          Estado del pago: {payment.status}
        </div>
      )}

      {canManage && (
        <div className="mt-6 border-t border-gray-100 pt-4 dark:border-gray-800">
          {mode === null && (
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setMode("pay")}
                className="rounded-lg bg-brand-500 px-4 py-2.5 text-sm font-medium text-white hover:bg-brand-600"
              >
                Pagar aquí
              </button>
              <button
                type="button"
                onClick={() => setMode("reschedule")}
                className="rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-white/3"
              >
                Reprogramar pago
              </button>
              <button
                type="button"
                onClick={() => setMode("validation")}
                className="rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-white/3"
              >
                Reportar pago realizado
              </button>
            </div>
          )}

          {mode === "pay" && (
            <WompiCheckoutForm
              payment={payment}
              currencyCode={credit.currencyCode}
              onDone={() => finish(true)}
              onCancel={() => setMode(null)}
            />
          )}

          {mode === "reschedule" && (
            <div className="flex flex-col gap-3">
              <label className="text-xs font-medium text-gray-500 dark:text-gray-400">
                Nueva fecha de pago (dentro de los próximos 30 días)
              </label>
              <input
                type="date"
                value={newDate}
                min={dateOnly(1)}
                max={dateOnly(30)}
                onChange={(e) => setNewDate(e.target.value)}
                className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-800 dark:border-gray-700 dark:bg-gray-800 dark:text-white/90"
              />
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setMode(null)}
                  disabled={submitting}
                  className="rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-400"
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  onClick={submitReschedule}
                  disabled={submitting || !newDate}
                  className="rounded-lg bg-brand-500 px-4 py-2.5 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50"
                >
                  {submitting ? "Enviando..." : "Enviar solicitud"}
                </button>
              </div>
            </div>
          )}

          {mode === "validation" && (
            <div className="flex flex-col gap-3">
              <label className="text-xs font-medium text-gray-500 dark:text-gray-400">
                Comprobante de pago (imagen, PDF o documento)
              </label>
              <input
                type="file"
                accept={RECEIPT_ACCEPT}
                multiple
                onChange={(e) => setFiles(e.target.files)}
                className="text-sm text-gray-700 file:mr-3 file:rounded-lg file:border-0 file:bg-gray-100 file:px-4 file:py-2 file:text-sm file:font-medium file:text-gray-700 dark:text-gray-300 dark:file:bg-gray-800 dark:file:text-gray-300"
              />
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setMode(null)}
                  disabled={submitting}
                  className="rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-400"
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  onClick={submitValidation}
                  disabled={submitting || !files || files.length === 0}
                  className="rounded-lg bg-brand-500 px-4 py-2.5 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50"
                >
                  {submitting ? "Enviando..." : "Enviar comprobante"}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="mt-6 flex justify-end">
        <button
          onClick={onClose}
          type="button"
          className="flex justify-center rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-white/3"
        >
          Cerrar
        </button>
      </div>
    </div>
  );
};
