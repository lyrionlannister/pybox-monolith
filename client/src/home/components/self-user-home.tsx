import { useMemo, useRef } from "react";
import { Calendar } from "@/ui/components/calendar/calendar";
import { getSession } from "@/auth/utils/auth-session-utils";
import { useMyCredits } from "@/credits/hooks/use-my-credits";
import { useCreditTypes } from "@/credits/hooks/use-credit-types";
import { useJudicialInbox } from "@/credits/hooks/use-judicial-inbox";
import { useJudicialPriorities } from "@/credits/hooks/use-judicial-priorities";
import { usePaymentStatuses } from "@/credits/hooks/use-payment-statuses";
import {
  buildObligationRows,
  buildObligationsSummary,
} from "@/credits/utils/obligations-summary-utils";
import { Breadcrumb } from "@/ui/components/common/breadcrumb";
import { getFirstName } from "../utils/home-session-utils";
import { SelfHomeHeader } from "./self-home-header";
import { SelfObligationsSummary } from "./self-obligations-summary";
import { SelfObligationsTable } from "./self-obligations-table";
import { SelfJudicialInbox } from "./self-judicial-inbox";
import { SelfHomeTips, SelfPayCard } from "./self-home-aside-cards";

export const SelfUserHome: React.FC = () => {
  const session = getSession();
  const firstName = getFirstName(session);
  const inboxRef = useRef<HTMLDivElement>(null);

  const { credits, loading, error, refetch } = useMyCredits();
  const { labels: creditTypeLabels } = useCreditTypes();
  const { labels: paymentStatusLabels } = usePaymentStatuses();
  const { labels: priorityLabels } = useJudicialPriorities();
  const { inbox, loading: loadingInbox, markRead } = useJudicialInbox();

  const summary = useMemo(() => buildObligationsSummary(credits), [credits]);
  const rows = useMemo(() => buildObligationRows(credits), [credits]);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <Breadcrumb pageTitle="Resumen" />

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto custom-scrollbar px-1 py-6 sm:px-2">
        <div className="flex w-full flex-col gap-6 pb-6">
          <SelfHomeHeader
            firstName={firstName ?? ""}
            unreadCount={inbox.unreadCount}
            onOpenInbox={() =>
              inboxRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })
            }
          />

          <SelfObligationsSummary summary={summary} loading={loading} />

          <div className="grid gap-6 xl:grid-cols-3 xl:items-stretch">
            <section className="xl:col-span-2">
              <h2 className="mb-3 text-base font-semibold text-gray-800 dark:text-white/90">
                Calendario de obligaciones
              </h2>
              <Calendar
                credits={credits}
                loading={loading}
                error={error}
                onRetry={refetch}
                entityLabel="Entidad"
              />
            </section>

            {/* Columna lateral: pagos y buzón, estirada a la altura del calendario */}
            <div className="flex flex-col gap-6">
              <SelfPayCard />
              <div ref={inboxRef} className="flex-1">
                <SelfJudicialInbox
                  items={inbox.items}
                  unreadCount={inbox.unreadCount}
                  priorityLabels={priorityLabels}
                  loading={loadingInbox}
                  onRead={markRead}
                />
              </div>
            </div>
          </div>

          <SelfObligationsTable
            rows={rows}
            creditTypeLabels={creditTypeLabels}
            paymentStatusLabels={paymentStatusLabels}
            loading={loading}
          />

          <SelfHomeTips />
        </div>
      </div>
    </div>
  );
};
