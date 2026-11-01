import { useCallback, useEffect, useState } from "react";

export type FileStatus = "checking" | "available" | "unavailable";

const isJsonResponse = (response: Response): boolean =>
  response.headers.get("content-type")?.includes("application/json") ?? false;

const checkFileAvailability = async (url: string): Promise<boolean> => {
  try {
    const headResponse = await fetch(url, {
      method: "HEAD",
      cache: "no-store",
      credentials: "include",
    });

    if (headResponse.status === 405 || headResponse.status === 501) {
      const controller = new AbortController();
      const getResponse = await fetch(url, {
        cache: "no-store",
        credentials: "include",
        headers: { Range: "bytes=0-0" },
        signal: controller.signal,
      });
      controller.abort();

      return getResponse.ok && !isJsonResponse(getResponse);
    }

    return headResponse.ok && !isJsonResponse(headResponse);
  } catch {
    return true;
  }
};

/** Verifica que un archivo (extracto, comprobante, etc.) sea alcanzable antes de
 * intentar mostrarlo en un iframe -- separado en un hook para que la lógica de
 * red sea testeable y reusable fuera de `FileViewerPage`. */
export const useFileAvailability = (url: string) => {
  const [fileStatus, setFileStatus] = useState<FileStatus>(url ? "checking" : "unavailable");

  useEffect(() => {
    let cancelled = false;

    if (!url) {
      setFileStatus("unavailable");
      return;
    }

    setFileStatus("checking");
    checkFileAvailability(url).then((available) => {
      if (!cancelled) {
        setFileStatus(available ? "available" : "unavailable");
      }
    });

    return () => {
      cancelled = true;
    };
  }, [url]);

  const retry = useCallback(() => {
    if (!url) return;
    setFileStatus("checking");
    checkFileAvailability(url).then((available) => {
      setFileStatus(available ? "available" : "unavailable");
    });
  }, [url]);

  return { fileStatus, retry };
};
