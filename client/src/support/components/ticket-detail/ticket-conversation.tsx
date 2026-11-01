import { useEffect, useRef, useState } from "react";
import { Lock, Send } from "lucide-react";
import { useTicketMessages } from "@/support/hooks/use-ticket-messages";
import { useSendTicketMessage } from "@/support/hooks/use-send-ticket-message";
import { useTicketPermissions } from "@/support/hooks/use-ticket-permissions";
import { useUserNameCache } from "@/support/hooks/use-user-name-cache";
import { Loader } from "@/ui/components/loader/loader";
import EmptyState from "@/ui/components/common/empty-state";
import { MessageSquare } from "lucide-react";
import { getSession } from "@/auth/utils/auth-session-utils";
import type { SupportTicketStatus } from "@/types/support/support-types";
import type { TicketConversationProps } from "@/support/types/ticket-conversation-props";

const TERMINAL: SupportTicketStatus[] = ["RESUELTO", "CERRADO"];

export const TicketConversation: React.FC<TicketConversationProps> = ({
  ticketNumber,
  status,
}) => {
  const session = getSession();
  const currentUserId = session?.userId;

  const { messages, loading } = useTicketMessages(ticketNumber);
  const { sendMessage, sending } = useSendTicketMessage(ticketNumber);
  const { canResolve, canAssign } = useTicketPermissions(status);
  const { getName: getSenderName } = useUserNameCache(messages, currentUserId);
  const isStaff = canResolve || canAssign;
  const isTerminal = TERMINAL.includes(status);

  const [body, setBody] = useState("");
  const [isInternal, setIsInternal] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const trimmed = body.trim();
    if (!trimmed || sending) return;
    const sent = await sendMessage({ body: trimmed, isInternal });
    if (sent) setBody("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSubmit();
    }
  };

  return (
    <div className="mt-6">
      <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
        Conversación
      </p>

      <div className="flex max-h-80 flex-col gap-3 overflow-y-auto custom-scrollbar rounded-xl border border-gray-100 bg-gray-50 p-4 dark:border-gray-800 dark:bg-white/3">
        {loading && (
          <Loader size="sm" loaderText="Cargando mensajes..." />
        )}
        {!loading && messages.length === 0 && (
          <EmptyState icon={MessageSquare} title="Sin mensajes aún" className="py-4" />
        )}
        {messages.map((msg) => {
          const isOwn = msg.senderId === currentUserId;
          return (
            <div key={msg.id} className={`flex flex-col ${isOwn ? "items-end" : "items-start"}`}>
              <div className="flex items-center gap-1.5 mb-0.5">
                {msg.isInternal && (
                  <Lock size={10} className="text-warning-500" />
                )}
                <span className="text-[10px] text-gray-400 dark:text-gray-500">
                  {getSenderName(msg.senderId)}
                </span>
              </div>
              <div
                className={`max-w-[80%] rounded-xl px-3 py-2 text-sm wrap-break-word ${
                  msg.isInternal
                    ? "border border-warning-200 bg-warning-50 text-warning-800 dark:border-warning-500/30 dark:bg-warning-500/10 dark:text-warning-300"
                    : isOwn
                      ? "bg-brand-500 text-white"
                      : "bg-white text-gray-800 border border-gray-100 dark:bg-gray-800 dark:text-white/90 dark:border-gray-700"
                }`}
              >
                {msg.body}
              </div>
              <span className="mt-0.5 px-1 text-[10px] text-gray-400 dark:text-gray-500">
                {new Date(msg.createdAt).toLocaleString("es-CO", {
                  day: "2-digit",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            </div>
          );
        })}
        <div ref={endRef} />
      </div>

      {!isTerminal && (
        <form onSubmit={handleSubmit} className="mt-3">
          {isStaff && (
            <div className="mb-2 flex items-center gap-2">
              <button
                type="button"
                onClick={() => setIsInternal((v) => !v)}
                className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                  isInternal
                    ? "bg-warning-100 text-warning-700 dark:bg-warning-500/20 dark:text-warning-400"
                    : "bg-gray-100 text-gray-500 hover:bg-gray-200 dark:bg-white/5 dark:text-gray-400 dark:hover:bg-white/10"
                }`}
              >
                <Lock size={10} />
                {isInternal ? "Nota interna" : "Visible al cliente"}
              </button>
            </div>
          )}
          <div className="flex items-end gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 focus-within:border-brand-300 dark:border-gray-700 dark:bg-gray-900 dark:focus-within:border-brand-500">
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={isInternal ? "Nota interna (solo agentes)..." : "Escribe un mensaje..."}
              rows={2}
              className="flex-1 resize-none bg-transparent text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none dark:text-white/90 dark:placeholder:text-white/30"
            />
            <button
              type="submit"
              disabled={!body.trim() || sending}
              className="mb-0.5 flex size-8 shrink-0 items-center justify-center rounded-full bg-brand-500 text-white transition-colors hover:bg-brand-600 disabled:opacity-40"
            >
              <Send size={14} />
            </button>
          </div>
        </form>
      )}
    </div>
  );
};
