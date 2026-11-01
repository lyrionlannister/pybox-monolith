import React, { useEffect } from "react";
import { useNavigate } from "react-router";
import { AdminLayout } from "@/ui/layouts/admin-layout";

/**
 * El access token vive en una cookie httpOnly: el frontend no puede leerlo ni
 * decodificarlo. Esta verificación es solo optimista (¿hay un perfil cacheado?);
 * la validación real ocurre en el backend — si la cookie falta o expiró, la
 * primera llamada autenticada devuelve 401 y useApiClient redirige a login.
 */
export const ProtectedRoute: React.FC = () => {
  const navigate = useNavigate();
  const userLogged = sessionStorage.getItem("user");
  const isValid = !!userLogged;

  useEffect(() => {
    if (!isValid) {
      sessionStorage.clear();
      navigate("/admin/sign-in", { replace: true });
    }
  }, [isValid, navigate]);

  if (!isValid) return null;

  return <AdminLayout />;
};
