import React, { useEffect, useState } from "react";
import { OtpInput } from "@/ui/components/inputs/otp-input";
import { useVerifyOtp } from "@/hooks/use-verify-otp";
import { Modal } from "@/ui/components/modal/modal";
import { Button } from "@/ui/components/button/button";
import type { MfaGuardProps } from "@/auth/types/mfa-guard-props";
import type { VerificationChannel } from "@/types/onboarding/onboarding-types";

export const MfaGuard: React.FC<MfaGuardProps> = ({ children }) => {
  const verified = sessionStorage.getItem("mfaVerified");
  const [done, setDone] = useState(verified === "true");
  // `done` se vuelve a poner en false en cada re-chequeo de MFA a mitad de sesión
  // (ver "mfa-pending" abajo). `layoutUnlockedOnce` en cambio solo pasa de false a
  // true UNA vez, la primera vez que se verifica en la sesión, y nunca se resetea:
  // gatea el PRIMER montaje de navbar/sidebar/chat (que ahora viven como hijos de
  // este guard), pero evita que un re-chequeo mid-sesión los desmonte y remonte
  // (perdiendo ventanas de chat abiertas o el estado del dropdown de notificaciones).
  // Los re-chequeos posteriores siguen bloqueando la interacción vía el modal de
  // OTP (fullscreen, se renderiza igual) sin volver a ocultar esa zona.
  const [layoutUnlockedOnce, setLayoutUnlockedOnce] = useState(verified === "true");
  const [channel, setChannel] = useState<VerificationChannel | null>(null);
  const [digits, setDigits] = useState<string[]>(Array(6).fill(""));
  const [codeSent, setCodeSent] = useState(false);
  const { requestOtp, verifyOtp, loading, error, clearError } = useVerifyOtp();

  useEffect(() => {
    // El backend exige el segundo factor en cada endpoint de negocio (no solo esta
    // pantalla): si el flag de sesión del servidor ya expiró pero este componente
    // seguía creyendo `done=true` por el `sessionStorage` viejo, cualquier request
    // de negocio dispara este evento (ver use-api-client.ts) y hay que volver a
    // pedir el OTP en vez de dejar al usuario viendo el mismo error repetido.
    const handleMfaPending = () => {
      setDone(false);
      setCodeSent(false);
      setChannel(null);
      setDigits(Array(6).fill(""));
      clearError();
    };
    window.addEventListener("mfa-pending", handleMfaPending);
    return () => window.removeEventListener("mfa-pending", handleMfaPending);
  }, [clearError]);

  const handleRequest = async (selectedChannel: VerificationChannel) => {
    clearError();
    setChannel(selectedChannel);
    await requestOtp(selectedChannel);
    setCodeSent(true);
  };

  const handleVerify = async () => {
    if (!channel) return;
    clearError();
    await verifyOtp(channel, digits.join(""));
    sessionStorage.setItem("mfaVerified", "true");
    setDone(true);
    setLayoutUnlockedOnce(true);
    // Red de seguridad: con navbar/sidebar/chat ahora montados como hijos de este
    // guard, su fetch inicial ya corre después de que `done` es true. Este evento
    // sigue siendo útil para hooks (ej. use-notifications.ts) que además quieran
    // refrescar explícitamente en cada verificación, no solo en el montaje.
    window.dispatchEvent(new Event("mfa-verified"));
  };

  const handleResend = () => {
    setCodeSent(false);
    setDigits(Array(6).fill(""));
    setChannel(null);
    clearError();
  };

  const otpModal = (
    <Modal isOpen onClose={() => {}} showCloseButton={false} isFullscreen className="flex bg-white dark:bg-gray-900">
      <div className="hidden lg:flex lg:w-80 xl:w-96 flex-col justify-between bg-brand-600 px-10 py-12 text-white shrink-0">
        <div>
          <div className="mb-12">
            <span className="text-2xl font-bold tracking-tight">PYBOX</span>
          </div>
          <div className="mb-3">
            <span className="text-sm font-medium text-brand-200 uppercase tracking-widest">
              Verificación de identidad
            </span>
          </div>
          <h1 className="text-3xl font-semibold leading-snug mb-2">
            Confirma tu acceso
          </h1>
          <p className="text-brand-200 text-sm leading-relaxed">
            Por seguridad, verificamos tu identidad en cada inicio de sesión.
          </p>
        </div>
        <div className="text-xs text-brand-300">Autenticación de dos factores</div>
      </div>

      <div className="flex flex-1 flex-col items-center justify-center px-6 py-6 sm:px-12 lg:px-16">
        <div className="w-full max-w-lg space-y-5">
          <div>
            <h2 className="text-lg font-semibold text-gray-800 dark:text-white/90">
              Verifica tu identidad
            </h2>
            <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
              Enviaremos un código de 6 dígitos para confirmar tu acceso.
            </p>
          </div>

          {!codeSent ? (
            <div className="flex flex-col gap-3">
              <Button
                type="button"
                size="sm"
                className="w-full"
                onClick={() => handleRequest("EMAIL")}
                loading={loading}
                loadingText="Enviando..."
              >
                Enviar código por correo
              </Button>
              <button
                type="button"
                disabled={loading}
                onClick={() => handleRequest("SMS")}
                className="flex w-full items-center justify-center rounded-lg border border-brand-500 px-4 py-3 text-sm font-medium text-brand-600 transition hover:bg-brand-50 disabled:opacity-50"
              >
                {loading ? "Enviando..." : "Enviar código por SMS"}
              </button>
            </div>
          ) : (
            <>
              <div className="space-y-3">
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  Ingresa el código de 6 dígitos enviado por{" "}
                  <span className="font-medium">
                    {channel === "EMAIL" ? "correo" : "SMS"}
                  </span>.
                </p>
                <OtpInput value={digits} onChange={setDigits} disabled={loading} error={!!error} />
                {error && <p className="text-xs text-error-500">{error}</p>}
              </div>
              <div className="flex flex-col gap-2">
                <Button
                  type="button"
                  size="sm"
                  className="w-full"
                  disabled={digits.join("").length < 6}
                  onClick={handleVerify}
                  loading={loading}
                  loadingText="Verificando..."
                >
                  Verificar
                </Button>
                <button
                  type="button"
                  disabled={loading}
                  onClick={handleResend}
                  className="text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400"
                >
                  Cambiar canal o reenviar código
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </Modal>
  );

  // Primer montaje de la sesión: no renderizar `children` (navbar/sidebar/chat
  // incluidos) hasta que el MFA quede verificado por primera vez.
  if (!layoutUnlockedOnce) return otpModal;

  // Ya desbloqueado alguna vez: `children` se mantiene montado siempre, y un
  // re-chequeo mid-sesión ("mfa-pending") solo superpone el modal de OTP sin
  // desmontar navbar/sidebar/chat.
  return (
    <>
      {children}
      {!done && otpModal}
    </>
  );
};
