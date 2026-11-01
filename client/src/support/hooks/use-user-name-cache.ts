import { useEffect, useRef, useState } from "react";
import { useApiClient } from "@/hooks/use-api-client";
import type { UserDetail } from "@/types/users/user-types";

/**
 * Resuelve y cachea nombres de usuario a partir de los ids vistos en `messages`,
 * evitando refetch repetido del mismo usuario.
 */
export const useUserNameCache = <T extends { senderId: string }>(
  messages: T[],
  currentUserId: string | undefined,
) => {
  const { apiClient } = useApiClient();
  const nameCache = useRef<Map<string, string>>(new Map());
  const [, forceRender] = useState(0);

  useEffect(() => {
    const unknown = messages
      .map((m) => m.senderId)
      .filter((id) => id !== currentUserId && !nameCache.current.has(id));
    const unique = [...new Set(unknown)];
    if (!unique.length) return;

    unique.forEach((id) => {
      apiClient(`/users/${id}`)
        .then((u: UserDetail) => {
          nameCache.current.set(id, u.fullName ?? `#${id}`);
          forceRender((n) => n + 1);
        })
        .catch(() => nameCache.current.set(id, `#${id}`));
    });
  }, [messages, apiClient, currentUserId]);

  const getName = (senderId: string): string => {
    if (senderId === currentUserId) return "Tú";
    return nameCache.current.get(senderId) ?? `#${senderId}`;
  };

  return { getName };
};
