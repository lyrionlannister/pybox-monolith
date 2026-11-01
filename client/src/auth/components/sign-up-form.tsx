import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router";
import { jwtDecode } from "jwt-decode";
import { Input } from "../../ui/components/inputs/input";
import { CountrySelect } from "../../ui/components/inputs/country-select";
import { Label } from "../../ui/components/inputs/label";
import { PasswordInput } from "../../ui/components/inputs/password-input";
import { SuccessModal } from "../../ui/components/modal/success-modal";
import { ErrorModal } from "../../ui/components/modal/error-modal";
import { Button } from "../../ui/components/button/button";
import { useModal } from "../../hooks/use-modal";
import { useRegister } from "../../hooks/use-register";
import { useOAuthRegister } from "../../hooks/use-oauth-register";
import { useCountries } from "../../hooks/use-countries";
import { GooglePayload } from "../../types/auth/google";
import { MANUAL_INITIAL } from "../../constants/auth/sign-up-form";
import { SignUpFormProps } from "../../types/props/sign-up-form-props";
import { GoogleButton } from "./google-button";

export const SignUpForm: React.FC<SignUpFormProps> = ({
  mode,
  onModeChange,
}) => {
  const [manualForm, setManualForm] = useState(MANUAL_INITIAL);
  const [phonePrefix, setPhonePrefix] = useState("");

  const {
    register,
    loading: loadingManual,
    error: errorManual,
  } = useRegister();
  const { oauthRegister, loading: loadingOAuth } = useOAuthRegister();
  const { countries, loading: loadingNationalities } = useCountries();
  const navigate = useNavigate();
  const successModal = useModal();
  const errorModal = useModal();
  const [countdown, setCountdown] = useState(10);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const loading = loadingManual || loadingOAuth;
  const error = errorManual;

  useEffect(() => {
    if (!successModal.isOpen) return;
    if (countdown === 0) {
      navigate("/home", { replace: true });
      return;
    }
    const timer = setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => clearTimeout(timer);
  }, [successModal.isOpen, countdown, navigate]);

  const sanitize = (err: unknown, fallback: string) => {
    if (!(err instanceof Error)) return fallback;
    if (
      err.message.toLowerCase().includes("network") ||
      err.message.toLowerCase().includes("fetch")
    )
      return "No se pudo conectar con el servidor. Verifica tu conexión.";
    return err.message || fallback;
  };

  const handleGoogleToken = async (token: string) => {
    try {
      const payload = jwtDecode<GooglePayload>(token);
      const endpoint = mode === "admin" ? "/auth/oauth" : "/auth/oauth/user";
      await oauthRegister({ provider: "GOOGLE", token }, endpoint);
      sessionStorage.setItem("user", JSON.stringify({ email: payload.email }));
      setCountdown(10);
      successModal.openModal();
    } catch (err) {
      setErrorMessage(sanitize(err, "Error al registrar con Google."));
      errorModal.openModal();
    }
  };

  const handleManualChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setManualForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  };

  const handleNationalityChange = (code: string) => {
    setManualForm((prev) => ({ ...prev, nationality: code }));
    const nation = countries.find((n) => n.code === code);
    if (nation) setPhonePrefix(nation.phonePrefix);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const prefix = phonePrefix ?? "";
      const endpoint =
        mode === "user" ? "/auth/register/user" : "/auth/register";
      await register(
        { ...manualForm, phoneNumber: prefix + manualForm.phoneNumber },
        endpoint,
      );
      setCountdown(10);
      successModal.openModal();
    } catch (err) {
      setErrorMessage(sanitize(err, "Error al registrar usuario."));
      errorModal.openModal();
    }
  };

  return (
    <div className="flex flex-col flex-1 overflow-y-auto custom-scrollbar">
      <div className="flex flex-col justify-center flex-1 w-full max-w-lg mx-auto py-8">
        <div className="mb-5 sm:mb-8">
          <h1 className="mb-2 font-semibold text-gray-800 text-title-sm dark:text-white/90 sm:text-title-md">
            {mode === "admin" ? "Registro de empresa" : "Registro de usuario"}
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {mode === "admin"
              ? "Crea la cuenta de tu empresa"
              : "Crea tu cuenta personal"}
          </p>
        </div>

        <div className="flex gap-1 p-1.5 mb-4 bg-gray-100 rounded-lg dark:bg-gray-800">
          {(["user", "admin"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => onModeChange(m)}
              className={`flex-1 py-2 text-sm font-medium rounded-md transition-colors ${
                mode === m
                  ? "bg-white text-gray-800 shadow-sm dark:bg-gray-700 dark:text-white"
                  : "text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
              }`}
            >
              {m === "admin" ? "Empresa" : "Usuario"}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit}>
          <div className="space-y-4 p-4">
            <div className="flex flex-row gap-2 items-center justify-between">
              <div>
                <Label htmlFor="signup-firstname" className="text-gray-500">
                  Nombre <span className="text-error-500">*</span>
                </Label>
                <Input
                  id="signup-firstname"
                  name="firstname"
                  placeholder="Tu nombre"
                  value={manualForm.firstname}
                  onChange={handleManualChange}
                  required
                  autoComplete="given-name"
                />
              </div>
              <div>
                <Label htmlFor="signup-lastname" className="text-gray-500">
                  Apellido <span className="text-error-500">*</span>
                </Label>
                <Input
                  id="signup-lastname"
                  name="lastname"
                  placeholder="Tu apellido"
                  value={manualForm.lastname}
                  onChange={handleManualChange}
                  required
                  autoComplete="family-name"
                />
              </div>
            </div>
            <div>
              <Label htmlFor="signup-email" className="text-gray-500">
                Correo electrónico <span className="text-error-500">*</span>
              </Label>
              <Input
                id="signup-email"
                type="email"
                name="email"
                placeholder="correo@ejemplo.com"
                value={manualForm.email}
                onChange={handleManualChange}
                required
                autoComplete="email"
              />
            </div>
            <PasswordInput
              id="signup-password"
              name="password"
              label="Contraseña *"
              placeholder="Ingresa tu contraseña"
              value={manualForm.password}
              onChange={handleManualChange}
              required
              autoComplete="new-password"
            />

            <div>
              <Label className="text-gray-500">
                Nacionalidad <span className="text-error-500">*</span>
              </Label>
              {/* CountrySelect no expone `id`, por lo que no puede enlazarse vía htmlFor
                  sin modificar ui/components/inputs/country-select.tsx (fuera de alcance). */}
              <CountrySelect
                mode="NAME"
                required
                countries={countries}
                placeholder={
                  loadingNationalities
                    ? "Cargando..."
                    : "Selecciona tu nacionalidad"
                }
                value={manualForm.nationality}
                onChange={handleNationalityChange}
                disabled={loadingNationalities}
              />
            </div>

            <div>
              <Label className="text-gray-500">
                Teléfono <span className="text-error-500">*</span>
              </Label>
              <div className="flex gap-2">
                <div className="w-28 shrink-0">
                  <CountrySelect
                    mode="PHONE"
                    valueKey="phonePrefix"
                    required
                    countries={countries}
                    placeholder="+"
                    value={phonePrefix}
                    onChange={setPhonePrefix}
                    className="pr-8"
                    disabled={loadingNationalities}
                  />
                </div>
                <div className="flex-1 min-w-0">
                  <Input
                    type="tel"
                    name="phoneNumber"
                    placeholder="300 000 0000"
                    value={manualForm.phoneNumber}
                    onChange={handleManualChange}
                    autoComplete="tel"
                    required
                  />
                </div>
              </div>
            </div>

            {error && <p className="text-sm text-error-500">{error}</p>}

            <Button type="submit" size="sm" className="w-full" loading={loading} loadingText="Registrando...">
              Crear cuenta
            </Button>
          </div>
        </form>

        <div className="relative py-4">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-gray-200 dark:border-gray-800" />
          </div>
          <div className="relative flex justify-center text-sm">
            <span className="px-4 py-1 text-gray-400 bg-white dark:bg-gray-900">
              O
            </span>
          </div>
        </div>

        <GoogleButton
          onToken={handleGoogleToken}
          text={
            loadingOAuth
              ? "Registrando con Google..."
              : "Registrarse con Google"
          }
          disabled={loading}
        />

        <div className="mt-5">
          <p className="text-sm font-normal text-center text-gray-700 dark:text-gray-400 sm:text-start">
            ¿Ya tienes cuenta?{" "}
            <Link
              to="/admin/sign-in"
              className="text-brand-500 hover:text-brand-600 dark:text-brand-400"
            >
              Inicia sesión
            </Link>
          </p>
        </div>
      </div>

      <SuccessModal
        isOpen={successModal.isOpen}
        title="¡Cuenta creada!"
        description={
          <>
            Tu cuenta fue registrada exitosamente. Serás redirigido al dashboard
            en{" "}
            <span className="font-semibold text-success-600 dark:text-success-500">
              {countdown}s
            </span>
            .
          </>
        }
        actionLabel="Ir al dashboard ahora"
        onAction={() => navigate("/home", { replace: true })}
      />

      <ErrorModal
        isOpen={errorModal.isOpen}
        onClose={errorModal.closeModal}
        title="Error al registrar"
        message={
          errorMessage ?? "Ocurrió un error inesperado. Intenta nuevamente."
        }
      />
    </div>
  );
};
