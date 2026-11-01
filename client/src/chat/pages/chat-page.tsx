import React, { KeyboardEvent, useEffect, useRef, useState } from "react";
import { ArrowLeft, MessageSquare, UsersRound, Users } from "lucide-react";
import { Loader } from "@/ui/components/loader/loader";
import { MessageBubble } from "@/ui/components/chat/message-bubble";
import { useChatPage } from "../hooks/use-chat-page";
import { NewGroupModal } from "../components/new-group-modal";
import { GroupMembersPanel } from "../components/group-members-panel";
import { CHAT_TYPE_GROUP } from "@/types/chat/chat-types";
import EmptyState from "@/ui/components/common/empty-state";

export const ChatPage: React.FC = () => {
  const {
    chats,
    chatsLoading,
    selected,
    availableUsers,
    showNewChat,
    showNewGroup,
    groupMembers,
    currentUserId,
    setShowNewChat,
    setShowNewGroup,
    selectChat,
    loadMore,
    sendMessage,
    openNewChat,
    createGroupChat,
    loadGroupMembers,
    addGroupMember,
    removeGroupMember,
    loadAvailableUsers,
    closeConversation,
  } = useChatPage();

  const [input, setInput] = useState("");
  const [search, setSearch] = useState("");
  const [showMembers, setShowMembers] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [selected?.messages.length]);

  useEffect(() => {
    setShowMembers(false);
  }, [selected?.chatId]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (el && el.scrollTop === 0 && selected?.nextCursor) {
      loadMore();
    }
  };

  const submit = () => {
    const trimmed = input.trim();
    if (!trimmed || !selected) return;
    sendMessage(trimmed);
    setInput("");
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const filteredChats = chats.filter((c) =>
    c.title.toLowerCase().includes(search.toLowerCase()),
  );

  const selectedSummary = chats.find((c) => c.id === selected?.chatId);

  return (
    <div className="flex h-[calc(100vh-174px)] gap-5 overflow-hidden">
      {/* Sidebar — en mobile ocupa toda la pantalla hasta que se selecciona un chat */}
      <div
        className={`${selected ? "hidden md:flex" : "flex"} flex-col w-full md:w-80 shrink-0 rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-dark overflow-hidden`}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-800">
          <h2 className="text-base font-semibold text-gray-800 dark:text-white/90">Chats</h2>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setShowNewGroup(true);
                loadAvailableUsers();
              }}
              aria-label="Nuevo grupo"
              title="Nuevo grupo"
              className="w-8 h-8 rounded-full bg-gray-100 text-gray-600 flex items-center justify-center hover:bg-gray-200 transition-colors dark:bg-white/5 dark:text-gray-300 dark:hover:bg-white/10"
            >
              <UsersRound size={16} />
            </button>
            <button
              type="button"
              onClick={() => {
                setShowNewChat(true);
                loadAvailableUsers();
              }}
              aria-label="Nuevo chat"
              className="w-8 h-8 rounded-full bg-brand-500 text-white flex items-center justify-center hover:bg-brand-600 transition-colors text-lg leading-none"
              title="Nuevo chat"
            >
              +
            </button>
          </div>
        </div>

        <div className="px-4 py-2 border-b border-gray-200 dark:border-gray-800">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar..."
            className="w-full bg-gray-50 dark:bg-gray-900 rounded-lg px-3 py-1.5 text-sm text-gray-800 dark:text-white/90 placeholder:text-gray-400 focus:outline-none"
          />
        </div>

        {showNewChat && (
          <div className="border-b border-gray-200 dark:border-gray-800 px-4 py-2 max-h-48 overflow-y-auto custom-scrollbar">
            {availableUsers.length === 0 ? (
              <EmptyState icon={Users} title="Sin usuarios disponibles" className="py-2" />
            ) : (
              availableUsers.map((u) => (
                <button
                  key={u.id}
                  type="button"
                  onClick={() => openNewChat(u.id)}
                  className="flex items-center gap-2 w-full py-1.5 hover:bg-gray-50 dark:hover:bg-white/5 rounded-lg px-2 text-left transition-colors"
                >
                  {u.profilePhotoUrl ? (
                    <img src={u.profilePhotoUrl} alt={u.fullName} className="w-8 h-8 rounded-full object-cover shrink-0" />
                  ) : (
                    <span className="w-8 h-8 rounded-full bg-brand-500 text-white text-xs font-semibold flex items-center justify-center shrink-0">
                      {u.fullName.charAt(0).toUpperCase()}
                    </span>
                  )}
                  <span className="text-sm text-gray-800 dark:text-white/90 truncate">{u.fullName}</span>
                </button>
              ))
            )}
          </div>
        )}

        <div className="flex-1 overflow-y-auto custom-scrollbar">
          {chatsLoading ? (
            <div className="mt-6"><Loader size="sm" /></div>
          ) : filteredChats.length === 0 ? (
            <EmptyState icon={MessageSquare} title="Sin conversaciones" className="mt-6" />
          ) : (
            filteredChats.map((chat) => (
              <button
                key={chat.id}
                type="button"
                onClick={() => selectChat(chat.id)}
                className={`flex items-center gap-3 w-full px-4 py-3 text-left border-b border-gray-200 dark:border-gray-800 transition-colors ${
                  selected?.chatId === chat.id
                    ? "bg-brand-50 dark:bg-brand-500/10"
                    : "hover:bg-gray-50 dark:hover:bg-white/5"
                }`}
              >
                {chat.peerAvatar ? (
                  <img src={chat.peerAvatar} alt={chat.title} className="w-10 h-10 rounded-full object-cover shrink-0" />
                ) : (
                  <span className="w-10 h-10 rounded-full bg-brand-500 text-white text-sm font-semibold flex items-center justify-center shrink-0">
                    {chat.title.charAt(0).toUpperCase()}
                  </span>
                )}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-gray-800 dark:text-white/90 truncate">{chat.title}</span>
                    {chat.unreadCount > 0 && (
                      <span className="ml-1 shrink-0 min-w-4.5 h-4.5 rounded-full bg-error-500 text-white text-theme-xs font-bold flex items-center justify-center px-1">
                        {chat.unreadCount > 99 ? "99+" : chat.unreadCount}
                      </span>
                    )}
                  </div>
                  {chat.lastMessage && (
                    <p className="text-xs text-gray-400 truncate mt-0.5">{chat.lastMessage}</p>
                  )}
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Chat panel — en mobile solo visible cuando hay una conversación seleccionada */}
      <div
        className={`${selected ? "flex" : "hidden md:flex"} flex-col flex-1 min-w-0 rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-dark overflow-hidden`}
      >
        {!selected ? (
          <div className="flex-1 flex items-center justify-center">
            <EmptyState icon={MessageSquare} title="Selecciona una conversación" />
          </div>
        ) : (
          <>
            <div className="relative flex items-center gap-3 px-5 py-3 border-b border-gray-200 dark:border-gray-800">
              <button
                type="button"
                onClick={closeConversation}
                aria-label="Volver a la lista de chats"
                className="md:hidden shrink-0 text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-white/80 transition-colors"
              >
                <ArrowLeft size={20} />
              </button>
              {selectedSummary?.peerAvatar ? (
                <img src={selectedSummary.peerAvatar} alt={selectedSummary.title} className="w-9 h-9 rounded-full object-cover" />
              ) : (
                <span className="w-9 h-9 rounded-full bg-brand-500 text-white text-sm font-semibold flex items-center justify-center">
                  {(selectedSummary?.title ?? "?").charAt(0).toUpperCase()}
                </span>
              )}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-gray-800 dark:text-white/90 truncate">
                  {selectedSummary?.title ?? ""}
                </p>
                {selectedSummary?.type === CHAT_TYPE_GROUP && (
                  <p className="text-xs text-gray-400">{selectedSummary.memberCount} miembros</p>
                )}
              </div>
              {selectedSummary?.type === CHAT_TYPE_GROUP && (
                <button
                  type="button"
                  onClick={() => {
                    setShowMembers((prev) => !prev);
                    loadGroupMembers(selectedSummary.id);
                    loadAvailableUsers();
                  }}
                  aria-label="Ver miembros del grupo"
                  title="Miembros"
                  className="shrink-0 w-8 h-8 rounded-full bg-gray-100 text-gray-600 flex items-center justify-center hover:bg-gray-200 transition-colors dark:bg-white/5 dark:text-gray-300 dark:hover:bg-white/10"
                >
                  <Users size={16} />
                </button>
              )}
              {showMembers && selectedSummary?.type === CHAT_TYPE_GROUP && (
                <GroupMembersPanel
                  isOpen={showMembers}
                  onClose={() => setShowMembers(false)}
                  members={groupMembers}
                  availableUsers={availableUsers}
                  currentUserId={currentUserId}
                  onAddMember={(userId) => addGroupMember(selectedSummary.id, userId)}
                  onRemoveMember={(userId) => removeGroupMember(selectedSummary.id, userId)}
                />
              )}
            </div>

            <div
              ref={scrollRef}
              onScroll={handleScroll}
              className="flex-1 overflow-y-auto custom-scrollbar px-5 py-4 flex flex-col gap-3"
            >
              {selected.loading && (
                <Loader size="sm" />
              )}
              {selected.nextCursor && !selected.loading && (
                <button
                  type="button"
                  onClick={loadMore}
                  className="text-xs text-brand-500 hover:underline self-center"
                >
                  Cargar más
                </button>
              )}
              {selected.messages.map((msg) => {
                const isOwn = msg.senderId === currentUserId;
                return (
                  <MessageBubble
                    key={msg.id}
                    body={msg.body}
                    isOwn={isOwn}
                    senderName={msg.senderName}
                    status={msg.status}
                    timestamp={new Date(msg.createdAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  />
                );
              })}
              <div ref={messagesEndRef} />
            </div>

            <div className="flex items-end gap-3 px-5 py-3 border-t border-gray-200 dark:border-gray-800">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Escribe un mensaje..."
                rows={1}
                className="flex-1 resize-none bg-gray-50 dark:bg-gray-900 rounded-xl px-4 py-2 text-sm text-gray-800 dark:text-white/90 placeholder:text-gray-400 focus:outline-none max-h-28 overflow-y-auto custom-scrollbar"
              />
              <button
                type="button"
                onClick={submit}
                disabled={!input.trim()}
                aria-label="Enviar mensaje"
                className="shrink-0 w-10 h-10 rounded-full bg-brand-500 text-white flex items-center justify-center hover:bg-brand-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4">
                  <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
                </svg>
              </button>
            </div>
          </>
        )}
      </div>

      <NewGroupModal
        isOpen={showNewGroup}
        onClose={() => setShowNewGroup(false)}
        availableUsers={availableUsers}
        onCreate={createGroupChat}
      />
    </div>
  );
};
