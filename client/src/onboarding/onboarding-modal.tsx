import React, { useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Modal } from "@/ui/components/modal/modal";
import { VerifyChannelStep } from "./steps/verify-channel-step";
import { SetPhoneStep } from "./steps/set-phone-step";
import { SetPasswordStep } from "./steps/set-password-step";
import { UpdateProfileStep } from "./steps/update-profile-step";
import { OrganizationStep } from "./steps/organization-step";
import { IdentityStep } from "./steps/identity-step";
import { useVerifyOtp } from "@/hooks/use-verify-otp";
import {
  STEP_DESCRIPTIONS,
  STEP_LABELS,
} from "@/onboarding/constants/onboarding-step-content";
import { buildOnboardingSteps } from "@/onboarding/utils/onboarding-step-utils";
import type { OnboardingModalProps } from "@/types/props/onboarding-props";

export const OnboardingModal: React.FC<OnboardingModalProps> = ({
  isOpen,
  status,
  onComplete,
}) => {
  const steps = buildOnboardingSteps(status);
  const [stepIndex, setStepIndex] = useState(0);
  const { requestOtp, verifyOtp, loading, error, clearError } = useVerifyOtp();

  const currentStep = steps[stepIndex];
  const progress = Math.round((stepIndex / steps.length) * 100);

  const next = () => {
    if (stepIndex + 1 >= steps.length) {
      onComplete();
    } else {
      setStepIndex((i) => i + 1);
    }
  };

  // Sin esto, un typo en un paso anterior (p. ej. el teléfono en set_phone) queda
  // sin forma de corregirse dentro del wizard: el usuario tenía que terminar todo
  // el onboarding y arreglarlo después desde perfil, si es que podía.
  const back = () => setStepIndex((i) => Math.max(0, i - 1));

  return (
    <Modal
      isOpen={isOpen}
      onClose={() => {}}
      showCloseButton={false}
      isFullscreen
      className="flex bg-white dark:bg-gray-900"
      ariaLabel={`Configuración de cuenta: ${STEP_LABELS[currentStep]}`}
    >
      <div className="hidden lg:flex lg:w-80 xl:w-96 flex-col justify-between bg-brand-600 px-10 py-12 text-white shrink-0">
        <div>
          <div className="mb-12">
            <span className="text-2xl font-bold tracking-tight">PYBOX</span>
          </div>

          <div className="mb-3">
            <span className="text-sm font-medium text-brand-200 uppercase tracking-widest">
              Configuración de cuenta
            </span>
          </div>
          <h1 className="text-3xl font-semibold leading-snug mb-2">
            Completa tu perfil
          </h1>
          <p className="text-brand-200 text-sm leading-relaxed">
            Necesitamos unos datos adicionales para activar tu cuenta.
          </p>

          <div className="mt-10 space-y-4">
            {steps.map((step, i) => {
              const isDone = i < stepIndex;
              const isCurrent = i === stepIndex;
              return (
                <div key={step} className="flex items-start gap-3">
                  <div
                    className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 text-xs font-bold transition-all ${
                      isDone
                        ? "border-brand-300 bg-brand-300 text-brand-700"
                        : isCurrent
                          ? "border-white bg-white text-brand-600"
                          : "border-brand-400 bg-transparent text-brand-400"
                    }`}
                  >
                    {isDone ? (
                      <svg
                        width="12"
                        height="12"
                        viewBox="0 0 12 12"
                        fill="none"
                      >
                        <path
                          d="M2 6l3 3 5-5"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    ) : (
                      i + 1
                    )}
                  </div>
                  <div>
                    <p
                      className={`text-sm font-medium ${
                        isCurrent
                          ? "text-white"
                          : isDone
                            ? "text-brand-200"
                            : "text-brand-400"
                      }`}
                    >
                      {STEP_LABELS[step]}
                    </p>
                    {isCurrent && (
                      <p className="mt-0.5 text-xs text-brand-200 leading-relaxed">
                        {STEP_DESCRIPTIONS[step]}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="text-xs text-brand-300">
          Paso {stepIndex + 1} de {steps.length}
        </div>
      </div>

      <div className="flex flex-1 flex-col">
        <div className="h-1 w-full bg-gray-100 dark:bg-gray-800">
          <div
            className="h-1 bg-brand-500 transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>

        <div className="flex flex-1 items-center justify-center px-6 py-6 sm:px-12 lg:px-16">
          <div className="w-full max-w-lg">
            <div className="mb-8 flex items-center gap-2 lg:hidden">
              {steps.map((step, i) => (
                <div
                  key={step}
                  className={`h-1.5 flex-1 rounded-full transition-all ${
                    i <= stepIndex
                      ? "bg-brand-500"
                      : "bg-gray-200 dark:bg-gray-700"
                  }`}
                />
              ))}
            </div>

            {stepIndex > 0 && (
              <button
                type="button"
                onClick={back}
                className="mb-4 inline-flex items-center gap-1.5 text-sm font-medium text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
              >
                <ArrowLeft size={15} />
                Atrás
              </button>
            )}

            {currentStep === "email" && (
              <VerifyChannelStep
                title="Verifica tu correo electrónico"
                description="Necesitamos confirmar que tienes acceso a tu correo."
                defaultChannel="EMAIL"
                onDone={next}
                requestOtp={requestOtp}
                verifyOtp={verifyOtp}
                loading={loading}
                error={error}
                clearError={clearError}
              />
            )}

            {currentStep === "set_password" && (
              <SetPasswordStep onDone={next} />
            )}

            {currentStep === "set_phone" && (
              <SetPhoneStep onDone={next} />
            )}

            {currentStep === "phone" && (
              <VerifyChannelStep
                title="Verifica tu número de teléfono"
                description="Confirma que tienes acceso a tu número registrado."
                defaultChannel="SMS"
                onDone={next}
                requestOtp={requestOtp}
                verifyOtp={verifyOtp}
                loading={loading}
                error={error}
                clearError={clearError}
              />
            )}

            {currentStep === "profile" && <UpdateProfileStep onDone={next} />}

            {currentStep === "organization" && (
              <OrganizationStep onDone={next} />
            )}

            {currentStep === "identity" && <IdentityStep onDone={next} />}
          </div>
        </div>
      </div>
    </Modal>
  );
};
