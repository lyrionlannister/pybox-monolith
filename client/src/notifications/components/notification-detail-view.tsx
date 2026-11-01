import { Link, useNavigate } from "react-router";
import { ArrowLeft } from "lucide-react";
import { Card, CardTitle } from "@/ui/components/card";
import { Button } from "@/ui/components/button/button";
import { timeAgo } from "@/ui/utils/time-utils";
import type { NotificationDetailViewProps } from "@/notifications/types/notification-detail-view-props";
import { NotifIcon } from "./notif-icon";
import { NOTIF_TYPE_BADGES as TYPE_BADGES, NOTIF_DETAIL_LABELS as DETAIL_LABELS } from "../constants/notification-detail-labels";

const toTitleCase = (key: string): string =>
  key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

const formatValue = (v: unknown): string => {
  if (typeof v === "number") return v.toLocaleString("es-CO");
  if (typeof v === "boolean") return v ? "Sí" : "No";
  return String(v ?? "—");
};

export const NotificationDetailView: React.FC<NotificationDetailViewProps> = ({ notification: n }) => {
  const navigate = useNavigate();
  const badge = TYPE_BADGES[n.notifType] ?? TYPE_BADGES.info;

  const detailEntries = n.details ? Object.entries(n.details) : [];

  return (
    <div className="flex flex-col gap-5">
      <Card>
        <div className="flex items-start gap-4">
          <NotifIcon type={n.notifType} size="lg" />
          <div className="min-w-0 flex-1">
            <h2 className="text-xl font-semibold text-gray-800 dark:text-white/90">
              {n.title}
            </h2>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
              <span>{n.category}</span>
              <span className="h-1 w-1 rounded-full bg-gray-300 dark:bg-gray-600" />
              <span>{timeAgo(n.createdAt)}</span>
              <span
                className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${badge.className}`}
              >
                {badge.label}
              </span>
            </div>
          </div>
        </div>

        <div className="mt-5">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">
            Mensaje del servidor
          </p>
          <div className="rounded-lg bg-gray-50 px-4 py-3 dark:bg-white/3">
            <p className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-line">
              {n.body}
            </p>
          </div>
        </div>
      </Card>

      {detailEntries.length > 0 && (
        <Card>
          <CardTitle>Detalles del proceso</CardTitle>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {detailEntries.map(([key, value]) => (
              <div
                key={key}
                className="rounded-lg border border-gray-100 bg-gray-50 px-4 py-3 dark:border-gray-800 dark:bg-white/3"
              >
                <p className="text-xs text-gray-400 dark:text-gray-500 mb-1">
                  {DETAIL_LABELS[key] ?? toTitleCase(key)}
                </p>
                <p className="text-base font-semibold text-gray-800 dark:text-white/90">
                  {formatValue(value)}
                </p>
              </div>
            ))}
          </div>
        </Card>
      )}

      <div className="flex items-center gap-3">
        {n.link ? (
          <Link
            to={n.link}
            className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 dark:bg-white dark:text-gray-900 dark:hover:bg-gray-100"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
              <polyline points="15 3 21 3 21 9" />
              <line x1="10" y1="14" x2="21" y2="3" />
            </svg>
            Ver
          </Link>
        ) : (
          <Button type="button" size="sm" variant="outline" startIcon={<ArrowLeft size={15} />} onClick={() => navigate(-1)}>
            Volver
          </Button>
        )}
      </div>
    </div>
  );
};
