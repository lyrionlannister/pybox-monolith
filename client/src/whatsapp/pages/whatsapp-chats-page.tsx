import React, { KeyboardEvent, useState } from "react";
import { useSearchParams } from "react-router";
import { MessageCircle, MoreVertical } from "lucide-react";
import { Loader } from "@/ui/components/loader/loader";
import EmptyState from "@/ui/components/common/empty-state";
import { Dropdown } from "@/ui/components/dropdown/dropdown";
import { DropdownItem } from "@/ui/components/dropdown/dropdown-item";
import { MessageBubble } from "@/ui/components/chat/message-bubble";
import { useWhatsAppChatsPage } from "../hooks/use-whatsapp-chats-page";
import { useWhatsAppChatDetails } from "../hooks/use-whatsapp-chat-details";
import { WhatsAppChatDetailsPanel } from "../components/whatsapp-chat-details-panel";
import type { WhatsAppChat } from "../types/whatsapp-chat-types";

const formatTime = (iso: string | null) => {
  if (!iso) return "";
  return new Date(iso).toLocaleString([], { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
};

export const WhatsAppChatsPage: React.FC = () => {
  // El hilo abierto vive en la URL (?chat=&org=&portfolio=): la lista mezcla hilos de
  // todas las organizaciones accesibles, así que la organización no es un estado de la
  // página sino una propiedad del hilo que se está viendo.
  const [searchParams, setSearchParams] = useSearchParams();
  const chatId = searchParams.get("chat") ?? "";
  const organizationId = searchParams.get("org") ?? "";

  const { chats, chatsLoading, selected, sending, withinServiceWindow, sendMessage } = useWhatsAppChatsPage(
    chatId,
    organizationId,
  );
  const { details, loading: detailsLoading, loadDetails, reset: resetDetails } = useWhatsAppChatDetails();

  const [input, setInput] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);

  const selectedChat = chats.find((c) => c.id === selected?.chatId);

  const openChat = (chat: WhatsAppChat) => {
    const params: Record<string, string> = { chat: chat.id, org: chat.organizationId };
    // Un hilo puede no tener portafolio resuelto (deudor que escribe sin envío previo),
    // en cuyo caso el param se omite en vez de quedar vacío.
    if (chat.portfolioId) params.portfolio = chat.portfolioId;
    setSearchParams(params);
  };

  const canSend = !!selected && !sending && !selected.loading && withinServiceWindow;

  const submit = async () => {
    const trimmed = input.trim();
    if (!trimmed || !canSend) return;
    // No se limpia el input hasta confirmar el envío: si falla, el agente no pierde
    // el mensaje ya escrito (puede traer montos/fechas específicas) y puede reintentar.
    const ok = await sendMessage(trimmed);
    if (ok) setInput("");
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const openDetails = () => {
    setMenuOpen(false);
    if (selected) {
      setDetailsOpen(true);
      loadDetails(selected.chatId, organizationId);
    }
  };

  const closeDetails = () => {
    setDetailsOpen(false);
    resetDetails();
  };

  return (
    <div className="flex h-[calc(100vh-174px)] gap-5 overflow-hidden">
      <div className="flex flex-col w-80 shrink-0 rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-dark overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-800">
          <h2 className="text-base font-semibold text-gray-800 dark:text-white/90">Chats de WhatsApp</h2>
        </div>

        <div className="flex-1 overflow-y-auto custom-scrollbar">
          {chatsLoading ? (
            <div className="mt-6">
              <Loader size="sm" />
            </div>
          ) : chats.length === 0 ? (
            <EmptyState icon={MessageCircle} title="Sin conversaciones asignadas" className="mt-6" />
          ) : (
            chats.map((chat) => {
              const title = chat.profileName || chat.phone;
              return (
                <button
                  key={chat.id}
                  type="button"
                  onClick={() => openChat(chat)}
                  className={`flex items-center gap-3 w-full px-4 py-3 text-left border-b border-gray-200 dark:border-gray-800 transition-colors ${
                    selected?.chatId === chat.id
                      ? "bg-brand-50 dark:bg-brand-500/10"
                      : "hover:bg-gray-50 dark:hover:bg-white/5"
                  }`}
                >
                  <span className="w-10 h-10 rounded-full bg-brand-500 text-white text-sm font-semibold flex items-center justify-center shrink-0">
                    {title.charAt(0).toUpperCase()}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-gray-800 dark:text-white/90 truncate">{title}</span>
                      <span className="ml-1 shrink-0 text-theme-xs text-gray-400">{formatTime(chat.lastMessageAt)}</span>
                    </div>
                    <p className="text-xs text-gray-400 truncate mt-0.5">{chat.phone}</p>
                  </div>
                </button>
              );
            })
          )}
        </div>
      </div>

      <div className="flex flex-col flex-1 min-w-0 rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-dark overflow-hidden">
        {!selected ? (
          <div className="flex-1 flex items-center justify-center">
            <EmptyState icon={MessageCircle} title="Selecciona una conversación" />
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between gap-3 px-5 py-3 border-b border-gray-200 dark:border-gray-800">
              <div className="flex items-center gap-3">
                <span className="w-9 h-9 rounded-full bg-brand-500 text-white text-sm font-semibold flex items-center justify-center">
                  {(selectedChat?.profileName || selectedChat?.phone || "?").charAt(0).toUpperCase()}
                </span>
                <div>
                  <p className="text-sm font-semibold text-gray-800 dark:text-white/90">
                    {selectedChat?.profileName || selectedChat?.phone}
                  </p>
                  <p className="text-xs text-gray-400">
                    {selectedChat?.phone}
                    {selectedChat?.organizationName ? ` · ${selectedChat.organizationName}` : ""}
                  </p>
                </div>
              </div>
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setMenuOpen((v) => !v)}
                  aria-label="Más opciones"
                  className="dropdown-toggle text-gray-400 hover:text-gray-700 dark:hover:text-gray-300"
                  title="Más opciones"
                >
                  <MoreVertical size={20} />
                </button>
                <Dropdown isOpen={menuOpen} onClose={() => setMenuOpen(false)} className="w-40 p-2">
                  <DropdownItem
                    onItemClick={openDetails}
                    className="flex w-full font-normal text-left text-gray-500 rounded-lg hover:bg-gray-100 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-white/5 dark:hover:text-gray-300"
                  >
                    Detalles
                  </DropdownItem>
                </Dropdown>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto custom-scrollbar px-5 py-4 flex flex-col gap-3">
              {selected.loading ? (
                <Loader size="sm" />
              ) : (
                selected.messages.map((msg) => (
                  <MessageBubble
                    key={msg.id}
                    body={msg.content ?? `[${msg.messageType}]`}
                    isOwn={msg.direction === "SALIENTE"}
                    timestamp={new Date(msg.sentAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  />
                ))
              )}
            </div>

            <div className="border-t border-gray-200 dark:border-gray-800">
              {!selected.loading && !withinServiceWindow && (
                <p className="px-5 pt-3 text-xs text-warning-600 dark:text-warning-500">
                  Pasaron más de 24h desde el último mensaje del deudor — no se pueden enviar mensajes libres hasta
                  que vuelva a escribir.
                </p>
              )}
              <div className="flex items-end gap-3 px-5 py-3">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={canSend ? "Escribe un mensaje..." : "Ventana de 24h cerrada"}
                  rows={1}
                  disabled={!canSend}
                  className="flex-1 resize-none bg-gray-50 dark:bg-gray-900 rounded-xl px-4 py-2 text-sm text-gray-800 dark:text-white/90 placeholder:text-gray-400 focus:outline-none max-h-28 overflow-y-auto custom-scrollbar disabled:cursor-not-allowed disabled:opacity-60"
                />
                <button
                  type="button"
                  onClick={submit}
                  disabled={!input.trim() || !canSend}
                  aria-label="Enviar mensaje"
                  className="shrink-0 w-10 h-10 rounded-full bg-brand-500 text-white flex items-center justify-center hover:bg-brand-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4">
                    <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
                  </svg>
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      <WhatsAppChatDetailsPanel open={detailsOpen} loading={detailsLoading} details={details} onClose={closeDetails} />
    </div>
  );
};
