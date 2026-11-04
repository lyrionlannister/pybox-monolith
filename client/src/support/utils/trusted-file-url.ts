import { API_URL } from "@/config/api";

/**
 * `true` solo si `url` apunta a la API o a la propia app. El visor la mete en un
 * iframe y la consulta con credenciales: cualquier otro origen permitiría mostrar
 * una página de phishing "dentro" de la app con un enlace a `/files/viewer?url=`.
 */
export const isTrustedFileUrl = (url: string, apiUrl: string = API_URL): boolean => {
  if (!url) return false;
  try {
    const target = new URL(url, window.location.origin);
    const allowed = new Set([window.location.origin]);
    if (apiUrl) allowed.add(new URL(apiUrl, window.location.origin).origin);
    return (target.protocol === "https:" || target.protocol === "http:") && allowed.has(target.origin);
  } catch {
    return false;
  }
};
