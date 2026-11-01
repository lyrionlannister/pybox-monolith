import React, { useEffect } from "react";
import { useChat } from "../hooks/use-chat";
import { AvailableUsersPanel } from "./available-users-panel";
import { ChatBubble } from "./chat-bubble";
import { ChatWindow } from "./chat-window";
import { useAuth } from "../../hooks/use-auth";

export const ChatBubblesContainer: React.FC = () => {
  const {
    chats,
    windows,
    availableUsers,
    showPanel,
    totalUnread,
    setShowPanel,
    loadAvailableUsers,
    loadChats,
    openChat,
    openExistingChat,
    closeWindow,
    minimizeWindow,
    expandWindow,
    sendMessage,
    loadMoreMessages,
  } = useChat();

  const { getSession } = useAuth();
  const session = getSession();
  const currentUserId = session?.userId ?? "";
  useEffect(() => {
    loadChats();
  }, [loadChats]);

  const handleLauncherClick = () => {
    if (!showPanel) {
      loadAvailableUsers();
    }
    setShowPanel((prev) => !prev);
  };

  const expandedWindows = windows.filter((w) => w.status === "expanded");
  const minimizedWindows = windows.filter((w) => w.status === "minimized");
  // En mobile (<sm) una ventana ya casi ocupa el ancho completo: solo se muestra la
  // última expandida, el resto queda oculta (sigue "abierta" en estado, solo no se pinta)
  // hasta un viewport sm+. El launcher/bubbles también se ocultan mientras haya una
  // ventana abierta en mobile, para no desbordar el layout fijo bottom/right.
  const hasExpandedWindow = expandedWindows.length > 0;

  return (
    <div className="fixed bottom-6 right-6 z-9999 flex items-end gap-3">
      {/* Expanded chat windows — rendered right to left */}
      {expandedWindows.map((win, index) => {
        const isLastExpanded = index === expandedWindows.length - 1;
        return (
          <div key={win.chatId} className={isLastExpanded ? "flex" : "hidden sm:flex"}>
            <ChatWindow
              window={win}
              currentUserId={currentUserId}
              onClose={() => closeWindow(win.chatId)}
              onMinimize={() => minimizeWindow(win.chatId)}
              onSend={(body) => sendMessage(win.chatId, body)}
              onLoadMore={() => loadMoreMessages(win.chatId)}
            />
          </div>
        );
      })}

      <div className={`${hasExpandedWindow ? "hidden sm:flex" : "flex"} flex-col items-end gap-2`}>
        <div className="flex flex-col gap-2">
          {minimizedWindows.map((win) => {
            const chat = chats.find((c) => c.id === win.chatId);
            return (
              <ChatBubble
                key={win.chatId}
                window={win}
                unreadCount={chat?.unreadCount ?? 0}
                onExpand={() => expandWindow(win.chatId)}
                onClose={() => closeWindow(win.chatId)}
              />
            );
          })}
        </div>

        <div className="relative">
          {showPanel && (
            <AvailableUsersPanel
              users={availableUsers}
              chats={chats}
              onSelect={(user) => openChat(user.id, user.fullName, user.profilePhotoUrl)}
              onOpenChat={openExistingChat}
              onClose={() => setShowPanel(false)}
            />
          )}

          <button
              type="button"
              onClick={handleLauncherClick}
              aria-label={showPanel ? "Cerrar panel de chats" : "Abrir panel de chats"}
              className="relative w-14 h-14 rounded-full bg-brand-500 text-white shadow-lg flex items-center justify-center hover:bg-brand-600 active:scale-95 transition-all focus:outline-none"
              title="Chats"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="currentColor"
                className="w-6 h-6"
              >
                <path
                  fillRule="evenodd"
                  d="M4.848 2.771A49.144 49.144 0 0112 2.25c2.43 0 4.817.178 7.152.52 1.978.292 3.348 2.024 3.348 3.97v6.02c0 1.946-1.37 3.678-3.348 3.97a48.901 48.901 0 01-3.476.383.39.39 0 00-.297.17l-2.755 4.133a.75.75 0 01-1.248 0l-2.755-4.133a.39.39 0 00-.297-.17 48.9 48.9 0 01-3.476-.384c-1.978-.29-3.348-2.024-3.348-3.97V6.741c0-1.946 1.37-3.68 3.348-3.97z"
                  clipRule="evenodd"
                />
              </svg>

              {totalUnread > 0 && (
                <span className="absolute -top-1 -right-1 min-w-5 h-5 rounded-full bg-error-500 text-white text-theme-xs font-bold flex items-center justify-center px-1 leading-none">
                  {totalUnread > 99 ? "99+" : totalUnread}
                </span>
              )}
            </button>
        </div>
      </div>
    </div>
  );
};
