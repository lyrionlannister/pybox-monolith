import { API_URL } from "@/config/api";

/**
 * El access token vive en una cookie httpOnly: EventSource la adjunta solo
 * (mismo sitio) siempre que se pida withCredentials. Ya no se pasa el token
 * por query string.
 */
export const openNotificationStream = (): EventSource =>
  new EventSource(`${API_URL}/notifications/stream`, { withCredentials: true });
