import { useState } from "react";
import { Bell } from "lucide-react";
import { ModuleBase } from "@/ui/components/common/module-base";
import { useNotifications } from "@/hooks/use-notifications";
import type { NotifType } from "@/types/notifications/notification";
import { FILTERS, FilterKey, TYPE_LABELS } from "@/constants/notifications/notification-filters";
import { NotificationRow } from "@/notifications/components/notification-row";
import { NotificationDetailView } from "@/notifications/components/notification-detail-view";
import EmptyState from "@/ui/components/common/empty-state";
import { Loader } from "@/ui/components/loader/loader";

export const NotificationsPage: React.FC = () => {
  const { notifications, loading, unreadCount, markAllRead } = useNotifications();
  const [filter, setFilter] = useState<FilterKey>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const filtered = filter === "all"
    ? notifications
    : notifications.filter((n) => n.notifType === filter);

  const selected = selectedId !== null
    ? notifications.find((n) => n.id === selectedId) ?? null
    : null;

  return (
    <ModuleBase pageTitle="Notificaciones">
      <div className="flex gap-0">
        <div
          className={`flex flex-col gap-4 shrink-0 lg:w-96 lg:border-r lg:border-gray-100 lg:pr-6 lg:dark:border-gray-800 ${
            selected ? "hidden lg:flex" : "flex w-full"
          }`}
        >
          <div className="flex items-center justify-between">
            <div>
              {unreadCount > 0 && (
                <span className="rounded-full bg-brand-500 px-2 py-0.5 text-xs font-medium text-white">
                  {unreadCount} nuevas
                </span>
              )}
            </div>
            {unreadCount > 0 && (
              <button
                type="button"
                onClick={markAllRead}
                className="flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-white/5"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12" /></svg>
                Marcar todo leído
              </button>
            )}
          </div>

          <div className="flex gap-2 flex-wrap">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors ${
                  filter === f.key
                    ? "border-gray-800 bg-gray-900 text-white dark:border-gray-200 dark:bg-white dark:text-gray-900"
                    : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50 dark:border-gray-700 dark:bg-transparent dark:text-gray-400 dark:hover:bg-white/5"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>

          {loading ? (
            <Loader variant="section" />
          ) : filtered.length === 0 ? (
            <EmptyState
              title={filter === "all" ? "No hay notificaciones" : `No hay notificaciones de tipo "${TYPE_LABELS[filter as NotifType] ?? filter}"`}
              className="py-20"
            />
          ) : (
            <div className="flex flex-col gap-2">
              {filtered.map((n) => (
                <NotificationRow
                  key={n.id}
                  notification={n}
                  isSelected={n.id === selectedId}
                  onClick={() => setSelectedId(n.id === selectedId ? null : n.id)}
                />
              ))}
            </div>
          )}
        </div>

        <div
          className={`min-w-0 flex-1 ${
            selected
              ? "flex flex-col lg:pl-6"
              : "hidden lg:flex items-center justify-center"
          }`}
        >
          {selected ? (
            <>
              <button
                type="button"
                onClick={() => setSelectedId(null)}
                className="mb-4 flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 lg:hidden"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="19" y1="12" x2="5" y2="12" />
                  <polyline points="12 19 5 12 12 5" />
                </svg>
                Volver a notificaciones
              </button>
              <NotificationDetailView notification={selected} />
            </>
          ) : (
            <EmptyState icon={Bell} title="Selecciona una notificación" />
          )}
        </div>
      </div>
    </ModuleBase>
  );
};
