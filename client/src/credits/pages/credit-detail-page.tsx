import { useMemo, useState } from "react";
import { useParams } from "react-router";
import { CreditCard } from "lucide-react";
import { useMyCredits } from "@/credits/hooks/use-my-credits";
import { useCreditSettlement } from "@/credits/hooks/use-credit-settlement";
import { formatCreditCurrency, formatPaymentDate } from "@/credits/utils/financial-calendar-utils";
import { PaymentMethodCard } from "@/ui/components/calendar/payment-method-card";
import { ModuleBase } from "@/ui/components/common/module-base";
import { Loader } from "@/ui/components/loader/loader";
import { Alert } from "@/ui/components/alert/alert";
import { CreditStatusBadge } from "@/credits/components/credit-status-badge";
import { Button } from "@/ui/components/button/button";

const RECEIPT_ACCEPT = ".jpg,.jpeg,.png,.pdf";

export const CreditDetailPage: React.FC = () => {
  const { creditId } = useParams<{ creditId: string }>();
  const { credits, loading, error, refetch } = useMyCredits();
  const { requestSettlement, submitting } = useCreditSettlement();

  const [showForm, setShowForm] = useState(false);
  const [files, setFiles] = useState<FileList | null>(null);

  const credit = useMemo(() => credits.find((c) => c.id === creditId), [credits, creditId]);

  const submit = async () => {
    if (!credit || !files || files.length === 0) return;
    const ok = await requestSettlement(credit.id, files);
    if (ok) {
      setShowForm(false);
      setFiles(null);
      refetch();
    }
  };

  return (
    <ModuleBase pageTitle="Detalle de la obligación" pageIcon={CreditCard} showBack>
      {loading && (
        <div className="py-20">
          <Loader />
        </div>
      )}
      {!loading && error && (
        <Alert variant="error" title="No se pudo cargar la obligación" message={error} />
      )}
      {!loading && !error && !credit && (
        <p className="text-sm text-gray-500 dark:text-gray-400">No se encontró la obligación.</p>
      )}

      {credit && (
        <div className="flex flex-col gap-6">
          <div className="flex items-start justify-between gap-2">
            <h5 className="font-semibold text-gray-800 text-theme-xl dark:text-white/90 lg:text-2xl">
              {credit.creditNumber}
            </h5>
            <CreditStatusBadge isActive={credit.isActive} settlementRequested={credit.settlementRequested} />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {credit.organizationName && (
              <div className="sm:col-span-2">
                <p className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">Empresa</p>
                <p className="text-sm text-gray-800 dark:text-white/90">{credit.organizationName}</p>
              </div>
            )}
            <div>
              <p className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">Saldo total</p>
              <p className="text-sm font-semibold text-gray-800 dark:text-white/90">
                {formatCreditCurrency(credit.totalCreditBalance, credit.currencyCode)}
              </p>
            </div>
            <div>
              <p className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">Saldo en mora</p>
              <p className="text-sm text-gray-800 dark:text-white/90">
                {formatCreditCurrency(credit.overduePrincipalBalance, credit.currencyCode)}
              </p>
            </div>
            <div>
              <p className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">Fecha de desembolso</p>
              <p className="text-sm text-gray-800 dark:text-white/90">{formatPaymentDate(credit.disbursedDate)}</p>
            </div>
            <div>
              <p className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">Rol</p>
              <p className="text-sm text-gray-800 dark:text-white/90">{credit.role}</p>
            </div>
          </div>

          {credit.paymentMethods.length > 0 && (
            <div>
              <p className="mb-3 text-xs font-medium text-gray-500 dark:text-gray-400">Métodos de pago aceptados</p>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {credit.paymentMethods.map((m) => (
                  <PaymentMethodCard key={m.id} method={m} />
                ))}
              </div>
            </div>
          )}

          {credit.payments.length > 0 && (
            <div>
              <p className="mb-3 text-xs font-medium text-gray-500 dark:text-gray-400">Pagos</p>
              <div className="overflow-x-auto rounded-lg border border-gray-100 dark:border-gray-800">
                <table className="min-w-full text-sm">
                  <thead className="bg-gray-50 text-left text-xs text-gray-500 dark:bg-white/3 dark:text-gray-400">
                    <tr>
                      <th className="px-3 py-2">Cuota</th>
                      <th className="px-3 py-2">Fecha límite</th>
                      <th className="px-3 py-2">Valor</th>
                      <th className="px-3 py-2">Estado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {credit.payments.map((p) => (
                      <tr key={p.id} className="border-t border-gray-100 dark:border-gray-800">
                        <td className="px-3 py-2 text-gray-800 dark:text-white/90">#{p.installmentNumber ?? "-"}</td>
                        <td className="px-3 py-2 text-gray-600 dark:text-gray-400">{formatPaymentDate(p.limitPayDate)}</td>
                        <td className="px-3 py-2 text-gray-800 dark:text-white/90">
                          {formatCreditCurrency(p.paymentAmount, credit.currencyCode)}
                        </td>
                        <td className="px-3 py-2 text-gray-600 dark:text-gray-400">{p.status ?? "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Dar de baja */}
          <div className="border-t border-gray-100 pt-5 dark:border-gray-800">
            {!credit.isActive ? (
              <p className="text-sm text-gray-500 dark:text-gray-400">Esta obligación ya fue dada de baja.</p>
            ) : credit.settlementRequested ? (
              <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-700 dark:border-amber-900 dark:bg-amber-900/20 dark:text-amber-300">
                Ya enviaste una solicitud de baja para esta obligación; está en revisión por la entidad.
              </p>
            ) : !showForm ? (
              <Button type="button" size="sm" onClick={() => setShowForm(true)}>
                Dar de baja la obligación
              </Button>
            ) : (
              <div className="flex flex-col gap-3">
                <label className="text-xs font-medium text-gray-500 dark:text-gray-400">
                  Comprobante de pago total (imagen, PDF o documento)
                </label>
                <input
                  type="file"
                  accept={RECEIPT_ACCEPT}
                  multiple
                  onChange={(e) => setFiles(e.target.files)}
                  className="text-sm text-gray-700 file:mr-3 file:rounded-lg file:border-0 file:bg-gray-100 file:px-4 file:py-2 file:text-sm file:font-medium file:text-gray-700 dark:text-gray-300 dark:file:bg-gray-800 dark:file:text-gray-300"
                />
                <div className="flex justify-end gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => { setShowForm(false); setFiles(null); }}
                    disabled={submitting}
                  >
                    Cancelar
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    onClick={submit}
                    disabled={!files || files.length === 0}
                    loading={submitting}
                    loadingText="Enviando..."
                  >
                    Enviar comprobante
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </ModuleBase>
  );
};
