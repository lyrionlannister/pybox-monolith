interface ChannelBadgeProps {
  label: string;
  className?: string;
}

/** Chip neutro para el canal de un envío (SMS/EMAIL/WHATSAPP/nombre de canal
 * configurado) -- compartido entre campaigns-table y templates-table. */
export const ChannelBadge: React.FC<ChannelBadgeProps> = ({ label, className = "" }) => (
  <span
    className={`inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-600 dark:bg-gray-800 dark:text-gray-300 ${className}`}
  >
    {label}
  </span>
);
