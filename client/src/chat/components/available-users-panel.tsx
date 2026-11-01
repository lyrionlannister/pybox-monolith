import React, { useEffect, useState } from "react";
import { Link } from "react-router";
import { resolveProfilePhotoUrl } from "@/profile/utils/profile-photo-url";
import type { AvailableUsersPanelProps } from "@/chat/types/available-users-panel-props";

const Avatar: React.FC<{ name: string; url: string | null; size?: number }> = ({ name, url, size = 8 }) => {
  const resolved = resolveProfilePhotoUrl(url);
  const dim = `w-${size} h-${size}`;
  return resolved ? (
    <img src={resolved} alt={name} className={`${dim} rounded-full object-cover shrink-0`} />
  ) : (
    <span className={`${dim} rounded-full bg-brand-500 text-white text-xs font-semibold flex items-center justify-center shrink-0`}>
      {name.charAt(0).toUpperCase()}
    </span>
  );
};

export const AvailableUsersPanel: React.FC<AvailableUsersPanelProps> = ({
  users,
  chats,
  onSelect,
  onOpenChat,
  onClose,
}) => {
  const [search, setSearch] = useState("");

  const filtered = users.filter((u) =>
    u.fullName.toLowerCase().includes(search.toLowerCase()),
  );

  const sortedChats = [...chats].sort((a, b) => {
    if ((b.unreadCount ?? 0) !== (a.unreadCount ?? 0)) return (b.unreadCount ?? 0) - (a.unreadCount ?? 0);
    return (b.lastMessageAt ?? "").localeCompare(a.lastMessageAt ?? "");
  });

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const target = e.target as Element;
      if (!target.closest("[data-chat-panel]")) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);

  return (
    <div
      data-chat-panel
      className="absolute bottom-16 right-0 w-72 bg-white dark:bg-gray-dark border border-gray-200 dark:border-gray-800 rounded-xl shadow-xl z-50 flex flex-col overflow-hidden"
    >
      {sortedChats.length > 0 && (
        <>
          <div className="px-3 pt-3 pb-1">
            <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
              Conversaciones
            </p>
          </div>
          <div className="overflow-y-auto custom-scrollbar max-h-44">
            {sortedChats.map((chat) => (
              <button
                key={chat.id}
                type="button"
                onClick={() => onOpenChat(chat.id, chat.title, chat.peerAvatar)}
                className="w-full flex items-center gap-2.5 px-3 py-2 hover:bg-gray-50 dark:hover:bg-white/5 transition-colors text-left"
              >
                <Avatar name={chat.title} url={chat.peerAvatar} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-gray-800 dark:text-white/90 truncate">{chat.title}</p>
                  {chat.lastMessage && (
                    <p className="text-xs text-gray-400 truncate">{chat.lastMessage}</p>
                  )}
                </div>
                {chat.unreadCount > 0 && (
                  <span className="shrink-0 min-w-5 h-5 rounded-full bg-error-500 text-white text-theme-xs font-bold flex items-center justify-center px-1">
                    {chat.unreadCount > 99 ? "99+" : chat.unreadCount}
                  </span>
                )}
              </button>
            ))}
          </div>
          <div className="mx-3 my-1 border-t border-gray-100 dark:border-gray-800" />
        </>
      )}

      <div className="px-3 pt-2 pb-1">
        <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1.5">
          Nueva conversación
        </p>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Buscar usuario..."
          className="w-full text-xs bg-gray-50 dark:bg-gray-900 rounded-md px-2 py-1.5 focus:outline-none text-gray-800 dark:text-white/90 placeholder:text-gray-400 dark:placeholder:text-white/30"
          autoFocus
        />
      </div>

      <div className="overflow-y-auto custom-scrollbar max-h-48">
        {filtered.length === 0 ? (
          <p className="text-xs text-gray-400 text-center py-4">Sin resultados</p>
        ) : (
          filtered.map((user) => (
            <button
              key={user.id}
              type="button"
              onClick={() => onSelect(user)}
              className="w-full flex items-center gap-2 px-3 py-2 hover:bg-gray-50 dark:hover:bg-white/5 transition-colors text-left"
            >
              <div className="relative shrink-0">
                <Avatar name={user.fullName} url={user.profilePhotoUrl} />
                <span
                  className={`absolute bottom-0 right-0 w-2.5 h-2.5 rounded-full border-2 border-white dark:border-gray-dark ${
                    user.isOnline ? "bg-success-500" : "bg-gray-400"
                  }`}
                />
              </div>
              <span className="text-sm text-gray-800 dark:text-white/90 truncate">{user.fullName}</span>
            </button>
          ))
        )}
      </div>

      <div className="px-3 py-2 border-t border-gray-200 dark:border-gray-800">
        <Link
          to="/chats"
          onClick={onClose}
          className="block rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-4 py-2 text-center text-sm font-medium text-gray-800 dark:text-white/90 hover:bg-gray-50 dark:hover:bg-white/5 transition-colors"
        >
          Ver todos los chats
        </Link>
      </div>
    </div>
  );
};
