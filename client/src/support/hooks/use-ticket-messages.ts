import { useEffect } from "react";
import { useApiClient } from "@/hooks/use-api-client";
import { useAsyncResource } from "@/hooks/use-async-resource";
import type { TicketMessage } from "@/types/support/support-types";
import { openNotificationStream } from "@/utils/notification-stream";

export const useTicketMessages = (ticketNumber: number | undefined) => {
  const { apiClient } = useApiClient();
  const { data: messages, loading, refetch, setData: setMessages } = useAsyncResource<TicketMessage[]>(
    () =>
      ticketNumber
        ? apiClient(`/cs/tickets/${ticketNumber}/messages`).then((data: TicketMessage[]) => data ?? [])
        : Promise.resolve([]),
    [],
    [ticketNumber],
  );

  // Listen for SSE notifications about new messages on this ticket
  useEffect(() => {
    if (!ticketNumber) return;
    if (!sessionStorage.getItem("user")) return;

    const es = openNotificationStream();
    es.addEventListener("notification", (e) => {
      try {
        const notif = JSON.parse(e.data) as { category?: string; details?: { ticket_number?: number } };
        if (
          notif.category === "support_message" &&
          notif.details?.ticket_number === ticketNumber
        ) {
          refetch();
        }
      } catch {
        // Notificación malformada: se descarta sin romper el stream.
      }
    });
    es.onerror = () => {};
    return () => es.close();
  }, [ticketNumber, refetch]);

  return { messages, loading, refetch, setMessages };
};
