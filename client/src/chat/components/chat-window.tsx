import React, { KeyboardEvent, useEffect, useRef, useState } from "react";
import { Loader } from "@/ui/components/loader/loader";
import { MessageBubble } from "@/ui/components/chat/message-bubble";
import { resolveProfilePhotoUrl } from "@/profile/utils/profile-photo-url";
import type { ChatMessage } from "../../types/chat/chat-types";
import type { ChatWindowProps } from "@/chat/types/chat-window-props";

export const ChatWindow: React.FC<ChatWindowProps> = ({
  window: win,
  currentUserId,
  onClose,
  onMinimize,
  onSend,
  onLoadMore,
}) => {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [win.messages.length]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (el && el.scrollTop === 0 && win.nextCursor) {
      onLoadMore();
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const submit = async () => {
    const trimmed = input.trim();
    if (!trimmed) return;
    // No se limpia el input hasta confirmar el envío: si falla (conexión caída,
    // timeout), el usuario no pierde lo que ya escribió y puede reintentar.
    const ok = await onSend(trimmed);
    if (ok) setInput("");
  };

  return (
    <div className="flex flex-col w-[calc(100vw-3rem)] sm:w-72 h-105 rounded-t-xl bg-white dark:bg-gray-dark shadow-xl border border-gray-200 dark:border-gray-800">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-200 dark:border-gray-800 rounded-t-xl">
        <div className="relative shrink-0">
          {resolveProfilePhotoUrl(win.peerAvatar) ? (
            <img
              src={resolveProfilePhotoUrl(win.peerAvatar)!}
              alt={win.title}
              className="w-8 h-8 rounded-full object-cover"
            />
          ) : (
            <span className="w-8 h-8 rounded-full bg-brand-500 text-white text-xs font-semibold flex items-center justify-center">
              {win.title.charAt(0).toUpperCase()}
            </span>
          )}
        </div>
        <span className="flex-1 text-sm font-medium text-gray-800 dark:text-white/90 truncate">
          {win.title}
        </span>
        <button
          type="button"
          onClick={onMinimize}
          aria-label="Minimizar chat"
          className="text-gray-400 hover:text-gray-600 dark:hover:text-white/70 px-1 text-base leading-none"
          title="Minimizar"
        >
          –
        </button>
        <button
          type="button"
          onClick={onClose}
          aria-label="Cerrar chat"
          className="text-gray-400 hover:text-gray-600 dark:hover:text-white/70 px-1 text-base leading-none"
          title="Cerrar"
        >
          ✕
        </button>
      </div>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto custom-scrollbar px-3 py-2 flex flex-col gap-2"
      >
        {win.loading && (
          <div className="mt-4"><Loader size="sm" /></div>
        )}
        {win.nextCursor && !win.loading && (
          <button
            type="button"
            onClick={onLoadMore}
            className="text-xs text-brand-500 hover:underline self-center"
          >
            Cargar más
          </button>
        )}
        {win.messages.map((msg: ChatMessage) => {
          const isOwn = msg.senderId === currentUserId;
          return (
            <MessageBubble
              key={msg.id}
              body={msg.body}
              isOwn={isOwn}
              senderName={msg.senderName}
              status={msg.status}
              maxWidthClassName="max-w-[85%]"
              timestamp={new Date(msg.createdAt).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })}
            />
          );
        })}
        <div ref={messagesEndRef} />
      </div>

      <div className="flex items-end gap-2 px-3 py-2 border-t border-gray-200 dark:border-gray-800">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Escribe un mensaje..."
          rows={1}
          className="flex-1 resize-none bg-transparent text-sm text-gray-800 dark:text-white/90 placeholder:text-gray-400 dark:placeholder:text-white/30 focus:outline-none py-1 max-h-20 overflow-y-auto custom-scrollbar"
        />
        <button
          type="button"
          onClick={submit}
          disabled={!input.trim()}
          aria-label="Enviar mensaje"
          className="shrink-0 w-8 h-8 rounded-full bg-brand-500 text-white flex items-center justify-center hover:bg-brand-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          title="Enviar"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="currentColor"
            className="w-4 h-4"
          >
            <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
          </svg>
        </button>
      </div>
    </div>
  );
};
